# settleup

![ci](../../actions/workflows/ci.yml/badge.svg)

Split shared expenses with roommates and get the **fewest payments** needed to settle up. A small FastAPI + SQLite service with a no-build web UI.

```bash
pip install -r requirements.txt
python -m settleup          # http://127.0.0.1:8000   (SETTLEUP_DB=path to choose the database file)
python -m pytest -q         # 41 tests
```
Open the page, create a group, and share the URL: the random link token is the group's access key. Interactive API docs are at `/docs`.

```bash
curl -s -X POST localhost:8000/api/groups -H 'content-type: application/json' -d '{"name":"Apt","members":["ana","ben","cy"]}'
curl -s -X POST localhost:8000/api/groups/<id>/expenses -H 'content-type: application/json' \
     -d '{"description":"Internet","payer":"ana","amount_cents":6000}'
curl -s localhost:8000/api/groups/<id>/balances
# {"balances":{"ana":4000,"ben":-2000,"cy":-2000},"transfers":[{"from":"ben","to":"ana","cents":2000},{"from":"cy","to":"ana","cents":2000}]}
```

## Design
- **`ledger.py` is pure logic, no I/O.** Splits are exact integer cents using the *largest-remainder method*, so `$10.00 / 3` is 3.33 + 3.33 + 3.34, never a lost cent. Supports equal, weighted shares, and exact-amount splits plus recorded settlements.
- **Debt simplification:** greedy matching of the largest debtor with the largest creditor. Each payment clears at least one person, so at most *n−1* payments (finding the true minimum is NP-hard; greedy is the standard practical choice).
- **Invariants are property-tested** over thousands of random ledgers: shares sum to the total, balances sum to zero, and applying the suggested payments zeroes everyone.
- **API:** pydantic validation (length/range limits), `422` for malformed input, `400` for domain errors (unknown member, bad exact sums), `404`/`409` where appropriate. All SQL is parameterised (a test attempts injection), and expense deletes are scoped to their group.
- **UI** is one static file that renders user text with `textContent` (no HTML injection).

## Mutation-checked
I deliberately broke the code (dropped the leftover-cent step, flipped a settlement sign, un-scoped the delete query) and confirmed the tests fail each time.

## Limits
No accounts or auth: anyone with the link can edit (the same model as a shared doc link). One currency. Not yet deployed. Next: user accounts, expense editing, multi-currency, and a Dockerfile + deployment.
