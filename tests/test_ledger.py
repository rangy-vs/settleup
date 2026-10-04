import random

import pytest

from settleup.ledger import Expense, LedgerError, Settlement, allocate, balances, simplify


# ---------- allocate ----------
def test_even_split():
    assert allocate(900, {"a": 1, "b": 1, "c": 1}) == {"a": 300, "b": 300, "c": 300}


def test_remainder_cents_are_distributed_not_lost():
    out = allocate(1000, {"a": 1, "b": 1, "c": 1})
    assert sum(out.values()) == 1000 and sorted(out.values()) == [333, 333, 334]


def test_weighted_split():
    assert allocate(1000, {"a": 3, "b": 1}) == {"a": 750, "b": 250}


def test_allocate_always_sums_to_total_property():
    rng = random.Random(1)
    for _ in range(2000):
        total = rng.randint(0, 10**7)
        w = {f"p{i}": rng.randint(1, 9) for i in range(rng.randint(1, 8))}
        out = allocate(total, w)
        assert sum(out.values()) == total and all(v >= 0 for v in out.values())
        # nobody is off by more than one cent from their exact proportional share
        wsum = sum(w.values())
        assert all(abs(out[k] - total * w[k] / wsum) < 1 for k in w)


def test_allocate_is_deterministic():
    w = {"zed": 1, "amy": 1, "bob": 1}
    assert allocate(100, w) == allocate(100, dict(reversed(list(w.items()))))


@pytest.mark.parametrize("total,w", [(-1, {"a": 1}), (10, {}), (10, {"a": 0}), (10, {"a": -1})])
def test_allocate_rejects_bad_input(total, w):
    with pytest.raises(LedgerError):
        allocate(total, w)


# ---------- expenses ----------
def test_exact_split_must_sum_to_total():
    assert Expense("a", 1000, "exact", {"a": 400, "b": 600}).owed() == {"a": 400, "b": 600}
    with pytest.raises(LedgerError, match="sum"):
        Expense("a", 1000, "exact", {"a": 400, "b": 500}).owed()


def test_unknown_split_type_and_nonpositive_amount():
    with pytest.raises(LedgerError):
        Expense("a", 100, "weird", {"a": 1}).owed()
    with pytest.raises(LedgerError):
        Expense("a", 0, "equal", {"a": 1}).owed()


# ---------- balances ----------
M = ["alice", "bob", "carol"]


def test_balances_basic():
    bal = balances(M, [Expense("alice", 3000, "equal", {m: 1 for m in M})])
    assert bal == {"alice": 2000, "bob": -1000, "carol": -1000}


def test_payer_not_in_split():
    bal = balances(M, [Expense("alice", 1000, "equal", {"bob": 1, "carol": 1})])
    assert bal == {"alice": 1000, "bob": -500, "carol": -500}


def test_settlement_reduces_debt():
    e = Expense("alice", 3000, "equal", {m: 1 for m in M})
    bal = balances(M, [e], [Settlement("bob", "alice", 1000)])
    assert bal["bob"] == 0 and bal["alice"] == 1000


def test_unknown_member_rejected():
    with pytest.raises(LedgerError, match="unknown member"):
        balances(M, [Expense("mallory", 100, "equal", {"alice": 1})])
    with pytest.raises(LedgerError, match="unknown member"):
        balances(M, [Expense("alice", 100, "equal", {"mallory": 1})])


# ---------- simplify ----------
def apply(bal, transfers):
    out = dict(bal)
    for a, b, c in transfers:
        out[a] += c
        out[b] -= c
    return out


def test_simplify_chain_collapses():
    # a owes b 10, b owes c 10  ->  a pays c 10 directly
    bal = balances(["a", "b", "c"], [Expense("b", 1000, "equal", {"a": 1}), Expense("c", 1000, "equal", {"b": 1})])
    assert simplify(bal) == [("a", "c", 1000)]


def test_simplify_empty_when_settled():
    assert simplify({"a": 0, "b": 0}) == []


def test_simplify_property_clears_everyone_with_few_payments():
    rng = random.Random(42)
    for _ in range(500):
        people = [f"p{i}" for i in range(rng.randint(2, 9))]
        exps = []
        for _ in range(rng.randint(1, 15)):
            parts = rng.sample(people, rng.randint(1, len(people)))
            exps.append(Expense(rng.choice(people), rng.randint(1, 50000), "equal", {p: 1 for p in parts}))
        bal = balances(people, exps)
        tx = simplify(bal)
        assert all(v == 0 for v in apply(bal, tx).values())          # everyone ends at exactly zero
        assert len(tx) <= len(people) - 1                             # at most n-1 payments
        assert all(c > 0 and a != b for a, b, c in tx)


def test_balances_sum_to_zero_property():
    rng = random.Random(7)
    people = ["a", "b", "c", "d"]
    for _ in range(300):
        e = Expense(rng.choice(people), rng.randint(1, 99999), "shares", {p: rng.randint(1, 5) for p in people})
        assert sum(balances(people, [e]).values()) == 0
