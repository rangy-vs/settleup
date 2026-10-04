"""Pure bill-splitting logic: exact integer-cent math, no I/O.

Invariants (property-tested): an expense's shares always sum to its total, balances always sum to
zero, and applying the simplified transfers settles every balance using at most (people - 1) payments."""
from __future__ import annotations

from dataclasses import dataclass, field


class LedgerError(ValueError):
    pass


def allocate(total: int, weights: dict[str, int]) -> dict[str, int]:
    """Split `total` cents proportionally to integer weights, largest-remainder method.
    Leftover cents go to the largest fractional remainders (ties broken by name for determinism)."""
    if total < 0:
        raise LedgerError("total must be non-negative")
    if not weights or any(w <= 0 for w in weights.values()):
        raise LedgerError("need at least one participant and all weights must be positive")
    wsum = sum(weights.values())
    out = {k: total * w // wsum for k, w in weights.items()}
    leftover = total - sum(out.values())
    for k in sorted(weights, key=lambda k: (-(total * weights[k] % wsum), k))[:leftover]:
        out[k] += 1
    return out


@dataclass(frozen=True)
class Expense:
    payer: str
    cents: int
    split_type: str                      # "equal" | "shares" | "exact"
    split: dict[str, int] = field(default_factory=dict)   # equal: {name: 1}; shares: weights; exact: cents

    def owed(self) -> dict[str, int]:
        if self.cents <= 0:
            raise LedgerError("amount must be positive")
        if self.split_type == "equal":
            return allocate(self.cents, {k: 1 for k in self.split})
        if self.split_type == "shares":
            return allocate(self.cents, self.split)
        if self.split_type == "exact":
            if any(v < 0 for v in self.split.values()):
                raise LedgerError("exact amounts cannot be negative")
            if sum(self.split.values()) != self.cents:
                raise LedgerError(f"exact amounts sum to {sum(self.split.values())}, expected {self.cents}")
            return dict(self.split)
        raise LedgerError(f"unknown split type {self.split_type!r}")


@dataclass(frozen=True)
class Settlement:
    payer: str      # who handed over money
    payee: str      # who received it
    cents: int


def balances(members: list[str], expenses: list[Expense], settlements: list[Settlement] = ()) -> dict[str, int]:
    """Net position per member in cents: positive = is owed money, negative = owes money."""
    bal = {m: 0 for m in members}
    for e in expenses:
        owed = e.owed()
        for who in {e.payer, *owed}:
            if who not in bal:
                raise LedgerError(f"unknown member {who!r}")
        bal[e.payer] += e.cents
        for who, c in owed.items():
            bal[who] -= c
    for s in settlements:
        for who in (s.payer, s.payee):
            if who not in bal:
                raise LedgerError(f"unknown member {who!r}")
        bal[s.payer] += s.cents
        bal[s.payee] -= s.cents
    assert sum(bal.values()) == 0, "ledger invariant violated"
    return bal


def simplify(bal: dict[str, int]) -> list[tuple[str, str, int]]:
    """Fewest-payments settlement via greedy matching of the largest debtor with the largest creditor.
    Each payment fully clears at least one person, so there are at most (people - 1) payments.
    (Finding the true minimum is NP-hard; this greedy is the standard practical approach.)"""
    creditors = sorted(((c, n) for n, c in bal.items() if c > 0), key=lambda x: (-x[0], x[1]))
    debtors = sorted(((-c, n) for n, c in bal.items() if c < 0), key=lambda x: (-x[0], x[1]))
    creditors, debtors = [list(x) for x in creditors], [list(x) for x in debtors]
    out = []
    while creditors and debtors:
        creditors.sort(key=lambda x: (-x[0], x[1]))
        debtors.sort(key=lambda x: (-x[0], x[1]))
        pay = min(creditors[0][0], debtors[0][0])
        out.append((debtors[0][1], creditors[0][1], pay))
        creditors[0][0] -= pay
        debtors[0][0] -= pay
        creditors = [c for c in creditors if c[0] > 0]
        debtors = [d for d in debtors if d[0] > 0]
    return out
