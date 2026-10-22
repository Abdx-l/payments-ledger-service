"""Transactional double-entry transfers with idempotency."""
import argparse
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts(id TEXT PRIMARY KEY,balance_cents INTEGER NOT NULL CHECK(balance_cents>=0));
CREATE TABLE IF NOT EXISTS transfers(id INTEGER PRIMARY KEY,idempotency_key TEXT UNIQUE NOT NULL,source TEXT NOT NULL,destination TEXT NOT NULL,amount_cents INTEGER NOT NULL CHECK(amount_cents>0));
CREATE TABLE IF NOT EXISTS entries(id INTEGER PRIMARY KEY,transfer_id INTEGER NOT NULL REFERENCES transfers(id),account_id TEXT NOT NULL REFERENCES accounts(id),delta_cents INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS entries_transfer ON entries(transfer_id);
"""


class LedgerError(Exception):
    pass


def connect(path):
    db = sqlite3.connect(path, timeout=30, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=30000")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(SCHEMA)
    return db


def create_account(db, ident, balance=0):
    if not ident or not isinstance(balance, int) or balance < 0:
        raise ValueError("invalid account or balance")
    db.execute("INSERT INTO accounts VALUES(?,?)", (ident, balance))


def transfer(db, source, destination, amount, key):
    if not key or source == destination or not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        raise ValueError("key, distinct accounts and positive integer cents required")
    db.execute("BEGIN IMMEDIATE")
    try:
        previous = db.execute("SELECT * FROM transfers WHERE idempotency_key=?", (key,)).fetchone()
        if previous:
            if (previous["source"], previous["destination"], previous["amount_cents"]) != (source, destination, amount):
                raise LedgerError("key reused for different transfer")
            db.commit()
            return previous["id"]
        origin = db.execute("SELECT balance_cents FROM accounts WHERE id=?", (source,)).fetchone()
        target = db.execute("SELECT balance_cents FROM accounts WHERE id=?", (destination,)).fetchone()
        if not origin or not target or origin[0] < amount:
            raise LedgerError("missing account or insufficient funds")
        db.execute("UPDATE accounts SET balance_cents=balance_cents-? WHERE id=?", (amount, source))
        db.execute("UPDATE accounts SET balance_cents=balance_cents+? WHERE id=?", (amount, destination))
        ident = db.execute("INSERT INTO transfers(idempotency_key,source,destination,amount_cents) VALUES(?,?,?,?)", (key, source, destination, amount)).lastrowid
        db.executemany("INSERT INTO entries(transfer_id,account_id,delta_cents) VALUES(?,?,?)", [(ident, source, -amount), (ident, destination, amount)])
        db.commit()
        return ident
    except BaseException:
        db.rollback()
        raise


def verify(db):
    return [dict(row) for row in db.execute("SELECT transfer_id,SUM(delta_cents) AS net,COUNT(*) AS entries FROM entries GROUP BY transfer_id HAVING net<>0 OR entries<>2")]


def serve(db_path, port):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != "/transfers":
                self.send_error(404)
                return
            try:
                size = int(self.headers.get("Content-Length", 0))
                if not 0 < size <= 10000:
                    raise ValueError("invalid body size")
                body = json.loads(self.rfile.read(size))
                with connect(db_path) as db:
                    ident = transfer(db, body["from"], body["to"], body["amount_cents"], self.headers.get("Idempotency-Key"))
                status, payload = 200, {"transfer_id": ident}
            except (ValueError, KeyError, LedgerError) as exc:
                status, payload = 400, {"error": str(exc)}
            raw = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["init", "transfer", "verify", "serve"])
    p.add_argument("source", nargs="?")
    p.add_argument("destination", nargs="?")
    p.add_argument("amount", nargs="?", type=int)
    p.add_argument("--key")
    p.add_argument("--db", default="ledger.db")
    p.add_argument("--port", type=int, default=8080)
    a = p.parse_args()
    if a.command == "serve":
        serve(a.db, a.port)
        return
    with connect(a.db) as db:
        if a.command == "init":
            create_account(db, "checking", 10000)
            create_account(db, "savings")
            print("Created checking and savings")
        elif a.command == "verify":
            problems = verify(db)
            print(json.dumps({"balanced": not problems, "problems": problems}))
        else:
            print(json.dumps({"transfer_id": transfer(db, a.source, a.destination, a.amount, a.key)}))


if __name__ == "__main__":
    main()

