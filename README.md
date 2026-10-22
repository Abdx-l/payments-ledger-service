# Payments Ledger Service

A double-entry ledger with SQLite transactions, idempotent transfers, and balance checks. Each successful transfer writes one negative and one positive entry whose sum is zero. `BEGIN IMMEDIATE` serializes writers, so concurrent transfers cannot overdraw the same account.

```sh
python ledger.py init --db ledger.db
python ledger.py transfer checking savings 2500 --key transfer-001 --db ledger.db
python ledger.py verify --db ledger.db
python -m unittest discover -s tests -v
```

Amounts are integer cents. `init` creates a sample checking account with 10000 cents and a zero-balance savings account. The optional local HTTP server accepts POST `/transfers` with `Idempotency-Key` and JSON `{ "from": "checking", "to": "savings", "amount_cents": 2500 }`. This is a portfolio ledger, with no integration to payment rails.

