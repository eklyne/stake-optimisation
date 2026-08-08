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
]


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
