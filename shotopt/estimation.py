"""How well do you actually know your win rate?

Every sizing decision here consumes a win rate, and that win rate is an estimate
with error bars - at exactly the stake the decision rule pushes you toward, which
is the one you have played least. This module makes that uncertainty a number
instead of a caveat.

The response is not to stop modelling. It is to feed a deliberately conservative
win rate into the sizing (`shaded_winrate`), which is what fractional Kelly is
for: you shade down to buy robustness against your own estimation error.
"""

from __future__ import annotations

import math

__all__ = [
    "winrate_stderr",
    "winrate_ci",
    "hands_for_precision",
    "shaded_winrate",
]

Z_95 = 1.959963984540054


def winrate_stderr(stdev: float, hands: int) -> float:
    """Standard error of a bb/100 win rate measured over `hands` hands.

    `stdev` is per 100 hands, so the sample size in those units is hands/100 and
    the error falls as its square root - which is why win rates converge so
    painfully slowly.
    """
    if stdev <= 0:
        raise ValueError(f"stdev must be positive, got {stdev}")
    if hands <= 0:
        raise ValueError(f"hands must be positive, got {hands}")
    return stdev / math.sqrt(hands / 100.0)


def winrate_ci(
    winrate: float, stdev: float, hands: int, z: float = Z_95
) -> tuple[float, float]:
    """Confidence interval on the win rate, as (low, high) in bb/100."""
    half_width = z * winrate_stderr(stdev, hands)
    return winrate - half_width, winrate + half_width


def hands_for_precision(stdev: float, precision: float, z: float = Z_95) -> float:
    """Hands needed to pin the win rate down to +/- `precision` bb/100.

        n = 100 * (z * sigma / e) ** 2

    Quadratic in the precision, so halving the error bar costs four times the
    volume. This is the number that makes "I'll just take a shot and see how it
    goes" quantitative: seeing how it goes takes hundreds of thousands of hands.
    """
    if stdev <= 0:
        raise ValueError(f"stdev must be positive, got {stdev}")
    if precision <= 0:
        raise ValueError(f"precision must be positive, got {precision}")
    return 100.0 * (z * stdev / precision) ** 2


def shaded_winrate(winrate: float, stdev: float, hands: int, z: float = 1.0) -> float:
    """A deliberately pessimistic win rate: the lower `z`-sigma bound.

    Feed this rather than the point estimate into the sizing functions when you
    want the allocation to respond to how much you have actually played a stake.
    On a small sample the shade is large and the tool holds you back; as volume
    accumulates it converges on the point estimate.

    Default z=1.0 - one standard error, not a 95% bound. A 95% shade on a thin
    sample goes negative and refuses to size the stake at all, which is a true
    statement about your knowledge but a useless one for making a decision.
    """
    return winrate - z * winrate_stderr(stdev, hands)
