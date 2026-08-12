"""How much risk is too much - the one rule that decides the answer.

`mix.best_allocation` is a single line of logic: take the highest EUR/hour mix that
is *acceptable*. Everything hinges on what acceptable means, and there are two
defensible answers to that, which this module makes interchangeable.

**Ruin.** `P(the bankroll ever reaches zero) <= t`. Analytic, free to evaluate, and
the classic bankroll-management framing. Its weakness is that it is an ALL-TIME,
play-forever number: it answers a question about an infinite future, and it treats
every path that survives as equally comfortable. A mix that halves your roll twice
a year and grinds it back is "safe" under this rule.

**Downswing.** `P(a peak-to-trough fall of X or worse within Y hands) <= p`. What a
losing stretch actually feels like, over a horizon you can picture. It has no
closed form - peak-to-trough drawdown grows without bound over unlimited time, so
there is nothing to invert - which is why it costs a simulation per candidate and
why the horizon Y must be stated.

Note what the second one is NOT: a fall below where you STARTED. Start on 10k, run
to 15k, fall back to 8k, and that is a 7k downswing but only a 2k loss below start.
`ruin.loss_below_start_quantile` covers the second and has a closed form; this
module deliberately does not use it, because losing 7k off a high is the thing that
actually makes a player move down.

Both rules are exposed through one interface so `mix`, `charts`, `deck` and `cli`
ask the same question and neither mode is special-cased at the call site. Each
tolerance also names the quantity it is judging on (`measure`), which is what the
frontier chart puts on its x-axis - so the picture always shows the constraint that
was actually applied.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from . import ruin, sim
from .config import RISK_MODES as MODES

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .config import Config
    from .mix import Allocation

__all__ = [
    "Tolerance", "RuinTolerance", "DownswingTolerance", "BothTolerance",
    "for_config", "MODES",
]

_SCREEN_MARGIN = 1.10
"""How far outside the limit a cheap estimate must land before it is trusted to reject.

The downswing test screens at `sim.SCREEN_PATHS` before paying for
`sim.TOLERANCE_PATHS`. A screened figure carries sampling noise, so rejecting
anything merely over the line would occasionally throw out a mix the accurate run
would have kept. Only rejections with 10% of headroom are taken on the cheap
estimate; everything nearer the line is decided properly.
"""


class Tolerance(Protocol):
    """The risk rule, as everything downstream sees it."""

    mode: str

    def measure(self, allocation: "Allocation", config: "Config") -> float:
        """The risk quantity this rule judges on. Lower is safer."""

    def limit(self, config: "Config") -> float:
        """The value of `measure` at which the rule stops admitting."""

    def admits(self, allocation: "Allocation", config: "Config") -> bool:
        """Is this mix acceptable?"""

    def describe(self, config: "Config") -> str:
        """One line naming the active rule, for the CLI header and the deck."""


class RuinTolerance:
    """`P(ever bust) <= ruin_tolerance`, playing this mix at a fixed size forever.

    Free: `risk_of_ruin` is already on every `Allocation`, computed analytically
    when it was scored. Nothing here simulates anything.
    """

    mode = "ruin"

    def measure(self, allocation: "Allocation", config: "Config") -> float:
        return allocation.risk_of_ruin

    def limit(self, config: "Config") -> float:
        return config.ruin_tolerance

    def admits(self, allocation: "Allocation", config: "Config") -> bool:
        return allocation.risk_of_ruin <= config.ruin_tolerance

    def describe(self, config: "Config") -> str:
        return f"ruin tolerance {config.ruin_tolerance:.2%} (all-time, fixed size)"


class DownswingTolerance:
    """`P(worst peak-to-trough fall >= X within Y hands) <= p`. Simulated.

    `measure` is the same statement read the other way round: the downswing you
    run at probability `p`, i.e. the `1 - p` quantile of the worst fall per
    simulated lifetime. That is directly comparable to X, and it is a money
    figure, which makes it the natural x-axis for a frontier chart.

    Returned in EUROS, like every other internal money value - the display
    currency is applied when it is printed, never here.
    """

    mode = "downswing"

    def _quantile(self, allocation: "Allocation", config: "Config", paths: int) -> float:
        return sim.drawdown_quantile(
            config,
            allocation,
            hands=config.downswing_hands,
            quantile=1.0 - config.downswing_probability,
            paths=paths,
        )

    def measure(self, allocation: "Allocation", config: "Config") -> float:
        return self._quantile(allocation, config, sim.TOLERANCE_PATHS)

    def limit(self, config: "Config") -> float:
        if config.downswing_amount_eur is None:
            # Only reachable if something bypassed `for_config`: the loader makes
            # the amount mandatory whenever this rule is the active one.
            raise ValueError("no downswing amount configured - set [risk] downswing_amount")
        return config.downswing_amount_eur

    def floor(self, allocation: "Allocation", config: "Config") -> float | None:
        """An EXACT analytic lower bound on `measure`, free of any simulation.

        Along any single path the deepest peak-to-trough fall is at least the
        deepest fall below the starting point - the start is just one of the
        highs the path has made. So pathwise

            max_drawdown >= loss_below_start

        and therefore the same inequality holds quantile by quantile. The
        right-hand side has a closed form (`ruin.loss_below_start_quantile`), so
        any mix whose ANALYTIC figure already exceeds the limit is guaranteed to
        exceed it once simulated, and can be rejected without paying for a run.

        This is what makes the walk in `mix.best_allocation` tractable. Without
        it the bold end of a six-thousand-allocation space has to be simulated
        one mix at a time, which exhausts the test budget long before the walk
        reaches anything admissible - and the optimiser then reports that nothing
        clears when something does.

        None when the mix loses money, where the bound says nothing useful.
        """
        if allocation.mean_eur_per_100 <= 0:
            return None
        return ruin.loss_below_start_quantile(
            allocation.mean_eur_per_100,
            allocation.stdev_eur_per_100,
            1.0 - config.downswing_probability,
        )

    def admits(self, allocation: "Allocation", config: "Config") -> bool:
        # A mix that loses money has no meaningful drawdown horizon - it just goes
        # down - and the simulation would be spent confirming it. Reject on the
        # cheap fact instead.
        if allocation.mean_eur_per_100 <= 0:
            return False
        limit = self.limit(config)

        # Free and exact: no sampling noise, so no margin is needed around it.
        floor = self.floor(allocation, config)
        if floor is not None and floor > limit:
            return False

        # Cheap and noisy: a margin, so sampling error cannot reject something
        # the accurate run would have kept.
        if self._quantile(allocation, config, sim.SCREEN_PATHS) > limit * _SCREEN_MARGIN:
            return False
        return self.measure(allocation, config) <= limit

    def describe(self, config: "Config") -> str:
        return (
            f"at most {config.downswing_probability:.0%} chance of a "
            f"{config.currency.fmt(config.downswing_amount_eur)} downswing "
            f"in {config.downswing_hands:,} hands"
        )


class BothTolerance:
    """Both rules at once: a mix must satisfy the ruin bar AND the downswing bar.

    The intersection, so the answer is whichever rule is stricter at your current
    bankroll - and which one that is changes on its own as the roll moves. At a
    small roll ruin binds and the downswing rule is slack; as the roll grows ruin
    falls away to nothing (see `charts._ruin_cannot_rank_figure`) and the
    downswing rule takes over. Setting both means never having to work out which
    framing is the live one today.

    They are genuinely different constraints, not two spellings of one. On a
    40k bankroll a 0.01% ruin bar happily admits a mix that runs a 33k
    peak-to-trough fall: ruin asks whether you survive, and a drawdown that deep
    leaves you technically solvent and practically finished.

    ORDER MATTERS. Ruin is analytic and free; the downswing rule costs a
    simulation. Testing ruin first turns every ruin-rejection into a free one.
    """

    mode = "both"

    def __init__(self) -> None:
        self.ruin = RuinTolerance()
        self.downswing = DownswingTolerance()

    def measure(self, allocation: "Allocation", config: "Config") -> float:
        """The downswing figure - the one with a scale worth plotting.

        A composite has no single natural measure: the two legs are a
        probability and a sum of money. The charts each draw their OWN axis and
        ask the relevant leg directly, so this exists only for callers that want
        one number, and the money one is the more legible of the two.
        """
        return self.downswing.measure(allocation, config)

    def limit(self, config: "Config") -> float:
        return self.downswing.limit(config)

    def admits(self, allocation: "Allocation", config: "Config") -> bool:
        return self.ruin.admits(allocation, config) and self.downswing.admits(
            allocation, config
        )

    def binding(self, allocation: "Allocation", config: "Config") -> str | None:
        """Which leg rejected this mix - or None if both admitted it.

        Reported rather than inferred, because "outside tolerance" is a much
        less useful sentence than "outside tolerance ON DOWNSWING, with eleven
        decades of ruin headroom going spare".
        """
        if not self.ruin.admits(allocation, config):
            return "ruin"
        if not self.downswing.admits(allocation, config):
            return "downswing"
        return None

    def slack(self, allocation: "Allocation", config: "Config") -> str:
        """How much room each leg had, so the tight one is obvious at a glance.

        Ruin headroom is quoted in DECADES, not as a multiple: the ratio runs to
        eleven figures on a healthy bankroll, and "162,563,262,847x of room" is a
        number nobody can read. Orders of magnitude are the scale it lives on.
        """
        import math

        ratio = config.ruin_tolerance / max(allocation.risk_of_ruin, 1e-300)
        room = (
            f"{math.log10(ratio):.0f} decades of room" if ratio > 100
            else f"{ratio:.1f}x of room"
        )
        depth = self.downswing.measure(allocation, config)
        headroom = config.downswing_amount_eur - depth
        return (
            f"ruin {allocation.risk_of_ruin:.1e} against a {config.ruin_tolerance:.2%} "
            f"bar ({room}); downswing {config.currency.fmt(depth)} against "
            f"{config.currency.fmt(config.downswing_amount_eur)} "
            f"({config.currency.fmt(headroom)} of room)"
        )

    def describe(self, config: "Config") -> str:
        return (
            f"{self.ruin.describe(config)} AND {self.downswing.describe(config)} "
            f"- whichever binds"
        )


def for_config(config: "Config") -> Tolerance:
    """The rule the config selected."""
    if config.risk_mode == "downswing":
        return DownswingTolerance()
    if config.risk_mode == "ruin":
        return RuinTolerance()
    if config.risk_mode == "both":
        return BothTolerance()
    raise ValueError(f"unknown risk mode {config.risk_mode!r}, expected one of {MODES}")


def axis_label(mode: str, config: "Config") -> str:
    """X-axis label for a frontier chart drawn on `mode`'s measure."""
    if mode == "downswing":
        return (
            f"Worst downswing at {config.downswing_probability:.0%} "
            f"over {config.downswing_hands:,} hands ({config.currency.code})"
        )
    return "Risk of ruin"
