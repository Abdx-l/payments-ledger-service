import tempfile
import threading
import unittest
from pathlib import Path
from ledger import LedgerError, connect, create_account, transfer, verify


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "ledger.db")
        self.db = connect(self.path)
        create_account(self.db, "a", 1000)
        create_account(self.db, "b")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_balance_and_idempotency(self):
        ident = transfer(self.db, "a", "b", 300, "k")
        self.assertEqual(ident, transfer(self.db, "a", "b", 300, "k"))
        with self.assertRaises(LedgerError):
            transfer(self.db, "a", "b", 400, "k")
        self.assertEqual(self.db.execute("SELECT balance_cents FROM accounts WHERE id='a'").fetchone()[0], 700)
        self.assertEqual(verify(self.db), [])

    def test_parallel_transfers_do_not_overdraw(self):
        results = []
        lock = threading.Lock()
        def worker(i):
            db = connect(self.path)
            try:
                transfer(db, "a", "b", 100, f"k{i}")
                result = True
            except LedgerError:
                result = False
            finally:
                db.close()
            with lock:
                results.append(result)
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(sum(results), 10)
        self.assertEqual(self.db.execute("SELECT balance_cents FROM accounts WHERE id='a'").fetchone()[0], 0)
        self.assertEqual(verify(self.db), [])

