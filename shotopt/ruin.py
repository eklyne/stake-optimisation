"""Risk of ruin and drawdown, for a stake played at a FIXED size.

The diffusion approximation behind all of this treats a poker win rate as a
Gaussian outcome stream with mean `winrate` and standard deviation `stdev`, both
per 100 hands, and the bankroll as a Brownian motion with drift. The standard
result is

    R = exp(-2 * mu * B / sigma**2)

for the probability of ever touching zero, where B is the bankroll in big blinds.

Note the "fixed size" qualifier. These functions are for a player who keeps
playing the same stake regardless of how the roll moves. The Kelly bettor, who
continuously rescales exposure to the current bankroll, has a *different*
drawdown law - see `kelly.rescaled_drawdown_probability`. Confusing the two is
the easiest way to get a badly wrong number out of this repo.
"""

from __future__ import annotations

import math

__all__ = [
    "effective_stdev",
    "risk_of_ruin",
    "bankroll_for_ruin",
    "drawdown_probability",
    "loss_below_start_quantile",
    "odds_against",
]


def odds_against(probability: float) -> str:
    """A probability as bookmakers' odds against: 1e-4 -> `10,000/1`.

    Risk of ruin arrives as a decimal with a run of leading zeros, which is the
    least readable form a small probability has. Odds-against is the form a poker
    player already reads fluently, and it makes the difference between 0.01% and
    0.0001% obvious instead of a zero-counting exercise.

    Capped, because the safe end of this ladder runs to 1e-129 and the literal
    odds there are a 130-digit integer - which is not a number, it is a wall.
    Anything rarer than one in a million collapses to a single band: no decision
    turns on whether a mix busts you once per million lifetimes or once per
    10^129, and printing the difference only invites someone to weigh it.

    Lives here rather than in the charts so the terminal and the slides can share
    one spelling without the text commands importing matplotlib.
    """
    if probability <= 0:
        return "<1M/1"
    if probability >= 1:
        return "certain"
    odds = 1.0 / probability
    if odds >= 1e6:
        return "<1M/1"
    return f"{odds:,.0f}/1"


def effective_stdev(stdev: float, tables: int, correlation: float = 0.0) -> float:
    """Standard deviation per 100 hands, inflated for simultaneous tables.

    The textbook ruin formula assumes hands arrive one at a time and are
    independent. Playing `tables` at once puts several hands in flight together,
    and those outcomes are correlated within a session (same opponents, same
    hero, same tilt). Modelled as an equicorrelated block:

        sigma_eff = sigma * sqrt(1 + rho * (tables - 1))

    `correlation` defaults to 0.0, which reproduces the independent case exactly.
    Any inflation is therefore a number the user consciously typed - this repo
    has no measurement of the true correlation and does not pretend to.
    """
    if stdev <= 0:
        raise ValueError(f"stdev must be positive, got {stdev}")
    if tables < 1:
        raise ValueError(f"tables must be at least 1, got {tables}")
    if not 0.0 <= correlation <= 1.0:
        raise ValueError(f"correlation must be in [0, 1], got {correlation}")
    return stdev * math.sqrt(1.0 + correlation * (tables - 1))


def risk_of_ruin(winrate: float, stdev: float, bankroll_bb: float) -> float:
    """Probability of ever busting, playing this stake forever at a fixed size.

    `winrate` and `stdev` are per 100 hands in bb; `bankroll_bb` is the bankroll
    in big blinds of this stake. A non-positive win rate returns 1.0 - a losing
    player busts with certainty given unlimited time, which is the honest answer
    rather than an error.
    """
    if stdev <= 0:
        raise ValueError(f"stdev must be positive, got {stdev}")
    if bankroll_bb <= 0:
        return 1.0
    if winrate <= 0:
        return 1.0
    return math.exp(-2.0 * winrate * bankroll_bb / stdev**2)


def bankroll_for_ruin(winrate: float, stdev: float, ruin: float) -> float:
    """Bankroll in bb needed to hold risk of ruin at or below `ruin`.

    The inverse of `risk_of_ruin`. Raises on a non-positive win rate: there is no
    finite bankroll that makes a losing player safe, and returning a large float
    would quietly imply otherwise.
    """
    if stdev <= 0:
        raise ValueError(f"stdev must be positive, got {stdev}")
    if winrate <= 0:
        raise ValueError(
            f"no finite bankroll bounds ruin at a non-positive win rate (got {winrate})"
        )
    if not 0.0 < ruin < 1.0:
        raise ValueError(f"ruin tolerance must be in (0, 1), got {ruin}")
    return -(stdev**2) * math.log(ruin) / (2.0 * winrate)


def loss_below_start_quantile(winrate: float, stdev: float, quantile: float) -> float:
    """How far BELOW THE STARTING BANKROLL you ever go, at a given probability.

    Read the name carefully - this is not "the worst downswing you will have",
    and the difference is large. Start on 10k, run up to 15k, fall back to 5k:
    that is a 5k loss below start and a 10k peak-to-trough drawdown. Only the
    first can bust you, so only the first is what ruin measures.

    For a bankroll following Brownian motion with positive drift, the all-time
    deepest excursion below the starting point is exponentially distributed:

        P(ever fall x below start) = exp(-2 * mu * x / sigma**2)

    which is precisely `risk_of_ruin` with x standing in for the bankroll.
    Inverting it gives the depth to expect at any probability, and the two ideas
    turn out to be one idea: **your risk tolerance IS a loss-below-start
    quantile.** A 1% risk of ruin means your bankroll equals the 99th-percentile
    lifetime loss below where you started.

    This one really is bounded over infinite time, because the drift keeps
    dragging the floor upward - the quantiles below are the forever figures, and
    a finite horizon gives slightly smaller ones. PEAK-TO-TROUGH drawdown has no
    such bound: given unlimited time it grows without limit, so quoting a
    lifetime figure for it is meaningless and it has to come from a simulation
    over a stated horizon instead.

    `quantile` is the probability of NOT exceeding the returned depth, so 0.5 is
    the median and 0.99 the one-in-a-hundred. Units follow the inputs: pass bb
    and get bb, pass euros per 100 hands and get euros.
    """
    if not 0.0 < quantile < 1.0:
        raise ValueError(f"quantile must be in (0, 1), got {quantile}")
    return bankroll_for_ruin(winrate, stdev, 1.0 - quantile)


def drawdown_probability(
    winrate: float, stdev: float, bankroll_bb: float, fraction: float
) -> float:
    """P(the bankroll ever falls by `fraction` of its current value).

    Same diffusion, absorbing barrier moved up from zero to (1 - fraction) * B.
    `fraction=1.0` is exactly `risk_of_ruin`.

    This is the number that matters more than ruin in practice: a 50% drawdown
    does not bust you, but it forces a move down to a lower-EV configuration, and
    you then compound at the worse rate until you climb back.
    """
    if not 0.0 < fraction <= 1.0:
        raise ValueError(f"fraction must be in (0, 1], got {fraction}")
    return risk_of_ruin(winrate, stdev, bankroll_bb * fraction)
