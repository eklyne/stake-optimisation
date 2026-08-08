"""The actual question: what DISTRIBUTION of stakes should the tables be at?

Picking one stake for all your volume is a false constraint. Volume is already
divisible across tables, so the real decision variable is the share of
simultaneous tables at each stake - 12x 100NL can be 10x 100NL + 2x 200NL, and
risk scales smoothly with the dial rather than jumping when you "take a shot".

This does NOT need a simulation. Tables deal independent hands, so a mix has a
computable mean and variance per 100 hands:

    mean = sum over stakes of (n_s / T) * mu_s * v_s          (euros)
    var  = sum over stakes of (n_s / T) * sigma_s**2 * v_s**2 (euros squared)

with n_s tables at stake s, T tables in total, and v_s the big blind in euros.
Both are in euros, so the ordinary ruin formula applies to the aggregate directly:
R = exp(-2 * mean * B / var). Set every table to one stake and this collapses
exactly to that stake's own row in `analysis` - which is asserted in the tests.

So the optimum is found by ENUMERATING every allocation and taking the highest
EUR/hour that stays inside tolerance. No search heuristics, no sampling, no
convergence question: for a realistic table count and a handful of stakes there
are a few thousand allocations, and the answer is exact.

What still needs the simulation is the DYNAMIC problem - the roll moves while you
play it, so the right mix is a function of the bankroll you have now, and the
object to optimise is a policy with move-up and move-down thresholds. Everything
here is a static snapshot at one bankroll.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from . import rates
from .config import Config, Stake

__all__ = [
    "Allocation",
    "MAX_ALLOCATIONS",
    "AllocationLimit",
    "enumerate_allocations",
    "evaluate",
    "all_allocations",
    "best_allocation",
    "frontier",
    "marginal_step_up",
]

MAX_ALLOCATIONS = 500_000
"""Guard against a combinatorial blow-up. The count is C(T + S - 1, S - 1), which
is small for realistic inputs (12 tables over 5 stakes is 1,820) but grows fast."""


class AllocationLimit(RuntimeError):
    """Raised when the enumeration would be too large to be worth doing exactly."""


@dataclass(frozen=True)
class Allocation:
    """One candidate distribution of tables across stakes."""

    counts: tuple[int, ...]
    """Tables at each stake, aligned to `config.stakes` order."""
    stakes: tuple[Stake, ...]
    mean_eur_per_100: float
    """Expected euros per 100 hands dealt across all tables."""
    variance_eur_per_100: float
    eur_per_hour: float
    risk_of_ruin: float
    within_tolerance: bool
    drawdown_50: float

    @property
    def label(self) -> str:
        """e.g. '10x 100NL + 2x 200NL'."""
        parts = [
            f"{count}x {stake.name}"
            for count, stake in zip(self.counts, self.stakes)
            if count
        ]
        return " + ".join(parts) if parts else "(no tables)"

    @property
    def stdev_eur_per_100(self) -> float:
        return math.sqrt(self.variance_eur_per_100)


def _count_allocations(tables: int, caps: tuple[int, ...]) -> int:
    """Exact number of allocations, computed without building them."""
    ways = [1] + [0] * tables
    for cap in caps:
        updated = [0] * (tables + 1)
        for total in range(tables + 1):
            if not ways[total]:
                continue
            for take in range(min(cap, tables - total) + 1):
                updated[total + take] += ways[total]
        ways = updated
    return ways[tables]


def enumerate_allocations(tables: int, caps: tuple[int, ...]):
    """Every way to split `tables` across len(caps) stakes, respecting caps.

    Yields tuples of counts summing to exactly `tables`.
    """
    if tables < 1:
        raise ValueError(f"tables must be at least 1, got {tables}")
    if not caps:
        raise ValueError("need at least one stake")

    total = _count_allocations(tables, caps)
    if total == 0:
        raise AllocationLimit(
            f"no allocation of {tables} tables fits the per-stake caps {list(caps)}"
        )
    if total > MAX_ALLOCATIONS:
        raise AllocationLimit(
            f"{total:,} allocations exceeds the {MAX_ALLOCATIONS:,} limit - "
            "reduce the table count or the number of stakes"
        )

    def walk(index: int, remaining: int, chosen: tuple[int, ...]):
        if index == len(caps) - 1:
            if remaining <= caps[index]:
                yield chosen + (remaining,)
            return
        for take in range(min(caps[index], remaining) + 1):
            yield from walk(index + 1, remaining - take, chosen + (take,))

    yield from walk(0, tables, ())


def evaluate(counts: tuple[int, ...], config: Config) -> Allocation:
    """Score one allocation: EUR/hour, risk of ruin, drawdown."""
    stakes = config.stakes
    if len(counts) != len(stakes):
        raise ValueError(f"expected {len(stakes)} counts, got {len(counts)}")
    tables = sum(counts)
    if tables < 1:
        raise ValueError("an allocation must place at least one table")

    mean = 0.0
    variance = 0.0
    for count, stake in zip(counts, stakes):
        if not count:
            continue
        share = count / tables
        # The haircut is charged on TOTAL tables in play, not on this stake's
        # share - attention is spread across the whole screen, not per stake.
        winrate = rates.effective_winrate(
            stake.winrate_bb100, tables, config.winrate_haircut_bb_per_table
        )
        mean += share * winrate * stake.bb_eur
        variance += share * (stake.stdev_bb100 * stake.bb_eur) ** 2

    # Same equicorrelation inflation as the single-stake path, applied to the
    # aggregate. At rho=0 this is inert; with all tables on one stake it
    # reproduces `ruin.effective_stdev` exactly.
    variance *= 1.0 + config.table_correlation * (tables - 1)

    bankroll = config.bankroll_eur
    if mean > 0 and variance > 0:
        exponent = -2.0 * mean * bankroll / variance
        risk = math.exp(exponent)
        drawdown_50 = math.exp(exponent * 0.5)
    else:
        risk = 1.0
        drawdown_50 = 1.0

    hands = rates.hands_per_hour(tables, config.hands_per_hour_per_table)
    return Allocation(
        counts=counts,
        stakes=stakes,
        mean_eur_per_100=mean,
        variance_eur_per_100=variance,
        eur_per_hour=mean * hands / 100.0,
        risk_of_ruin=min(risk, 1.0),
        within_tolerance=risk <= config.ruin_tolerance,
        drawdown_50=min(drawdown_50, 1.0),
    )


def all_allocations(config: Config) -> list[Allocation]:
    """Every allocation of the configured table count, scored."""
    # `is not None`, not truthiness: max_tables = 0 means "I cannot get a seat
    # here at all", which is a meaningful setting and must not read as "no cap".
    caps = tuple(
        min(stake.max_tables, config.tables) if stake.max_tables is not None else config.tables
        for stake in config.stakes
    )
    return [evaluate(counts, config) for counts in enumerate_allocations(config.tables, caps)]


def best_allocation(allocations: list[Allocation]) -> Allocation | None:
    """Highest EUR/hour that stays inside tolerance - the decision rule, applied.

    Ties on EUR/hour are broken toward the lower risk, which matters more often
    than it sounds: two different mixes can earn near-identical hourly rates at
    very different variance.
    """
    inside = [a for a in allocations if a.within_tolerance]
    if not inside:
        return None
    return max(inside, key=lambda a: (a.eur_per_hour, -a.risk_of_ruin))


def frontier(allocations: list[Allocation]) -> list[Allocation]:
    """The efficient frontier: allocations no other allocation dominates.

    An allocation is dominated if another earns at least as much per hour at
    strictly lower risk. What survives is the menu of real trade-offs - the only
    mixes worth considering at any tolerance, not just your current one.
    """
    ordered = sorted(allocations, key=lambda a: (a.risk_of_ruin, -a.eur_per_hour))
    best_so_far = float("-inf")
    kept: list[Allocation] = []
    for allocation in ordered:
        if allocation.eur_per_hour > best_so_far:
            kept.append(allocation)
            best_so_far = allocation.eur_per_hour
    return kept


def marginal_step_up(
    allocation: Allocation, config: Config
) -> tuple[Allocation, float, float] | None:
    """Move one table up to the next stake: what it buys, and what it costs.

    Returns (new allocation, EUR/hour gained, ruin added), or None if there is no
    table that can move up. This is the question that actually gets asked at the
    table - not "what is optimal" but "can I put one more table up a level?"
    """
    counts = list(allocation.counts)
    # Move the highest-stake table that still has somewhere to go.
    for index in range(len(counts) - 2, -1, -1):
        if counts[index] > 0:
            counts[index] -= 1
            counts[index + 1] += 1
            stepped = evaluate(tuple(counts), config)
            return (
                stepped,
                stepped.eur_per_hour - allocation.eur_per_hour,
                stepped.risk_of_ruin - allocation.risk_of_ruin,
            )
    return None
