"""Kelly sizing for a continuous, roughly-Gaussian outcome stream.

For a repeated favourable bet with a re-invested bankroll, the growth-optimal
exposure is the one that maximises the expected LOGARITHM of the bankroll, not
expected profit. For a Gaussian stream that reduces to `f* = mu / sigma**2` -
edge over variance.

The poker translation matters and is easy to get backwards. The divisible
variable is not "what fraction of my roll do I bet" - poker gives you no such
dial. It is the STAKE. Playing 100NL with a EUR5,000 roll is an exposure choice
in exactly Kelly's sense, so the useful forms here are "what stake does this roll
support" and "what roll does this stake need".

All win rates and standard deviations are per 100 hands, in big blinds.
"""

from __future__ import annotations

__all__ = [
    "optimal_bankroll_bb",
    "required_bankroll_bb",
    "optimal_bb_eur",
    "growth_rate",
    "fractional_growth",
    "fractional_variance_ratio",
    "rescaled_drawdown_probability",
]


def _check(winrate: float, stdev: float) -> None:
    if stdev <= 0:
        raise ValueError(f"stdev must be positive, got {stdev}")
    if winrate <= 0:
        raise ValueError(f"Kelly sizing is undefined at a non-positive win rate (got {winrate})")


def optimal_bankroll_bb(winrate: float, stdev: float) -> float:
    """Full-Kelly bankroll for this stake, in big blinds: `sigma**2 / mu`.

    Worth having a feel for the magnitude: mu=5, sigma=90 gives 1620bb, i.e. 16
    buy-ins at full Kelly and 32 at half. The conventional 20/30/50-buy-in rules
    are in the same neighbourhood - which is the point. They are a serviceable
    proxy for this calculation, not an independent piece of wisdom.
    """
    _check(winrate, stdev)
    return stdev**2 / winrate


def required_bankroll_bb(winrate: float, stdev: float, kelly_fraction: float = 1.0) -> float:
    """Bankroll in bb needed to play this stake at `kelly_fraction` of full Kelly.

    Exposure scales with the roll, so playing at fraction k needs 1/k times the
    full-Kelly roll: half Kelly wants twice the bankroll.
    """
    if not 0.0 < kelly_fraction <= 1.0:
        raise ValueError(f"kelly_fraction must be in (0, 1], got {kelly_fraction}")
    return optimal_bankroll_bb(winrate, stdev) / kelly_fraction


def optimal_bb_eur(
    bankroll_eur: float, winrate: float, stdev: float, kelly_fraction: float = 1.0
) -> float:
    """The big blind, in euros, that this bankroll supports.

    The inverse reading of `required_bankroll_bb`, and usually the more useful one
    at the table: it answers "what stake am I actually rolled for" in money rather
    than in buy-ins. Round DOWN to a real stake - stakes come in discrete rungs and
    Kelly punishes overbetting far harder than underbetting.
    """
    if bankroll_eur <= 0:
        raise ValueError(f"bankroll must be positive, got {bankroll_eur}")
    return bankroll_eur / required_bankroll_bb(winrate, stdev, kelly_fraction)


def growth_rate(winrate: float, stdev: float) -> float:
    """Full-Kelly log-bankroll growth rate per 100 hands: `mu**2 / (2 * sigma**2)`."""
    _check(winrate, stdev)
    return winrate**2 / (2.0 * stdev**2)


def fractional_growth(winrate: float, stdev: float, kelly_fraction: float) -> float:
    """Growth rate at `kelly_fraction` of full Kelly: `k * (2 - k)` of the full rate.

    The shape is the whole argument for betting fractionally. It peaks at k=1 and
    is symmetric about it, so k=2 gives ZERO growth - betting at twice the optimal
    fraction is no better than not playing. Underbetting is gentle (k=0.5 keeps
    three quarters of the growth), overbetting is brutal. Since a poker win rate
    is always an estimate, shading down is the cheap side to err on.

    Accepts k > 1 so the penalty is visible; growth goes negative beyond k=2.
    """
    if kelly_fraction <= 0:
        raise ValueError(f"kelly_fraction must be positive, got {kelly_fraction}")
    return kelly_fraction * (2.0 - kelly_fraction) * growth_rate(winrate, stdev)


def fractional_variance_ratio(kelly_fraction: float) -> float:
    """Variance at fraction k, relative to full Kelly: `k**2`.

    With `fractional_growth` this is the trade-off in two numbers - half Kelly buys
    three quarters of the growth for a quarter of the variance.
    """
    if kelly_fraction <= 0:
        raise ValueError(f"kelly_fraction must be positive, got {kelly_fraction}")
    return kelly_fraction**2


def rescaled_drawdown_probability(fraction: float, kelly_fraction: float = 1.0) -> float:
    """P(a Kelly bettor's roll ever falls to `fraction` of its starting value).

        P = fraction ** (2 / k - 1)

    At full Kelly this collapses to `fraction` itself - so a 50% drawdown is a coin
    flip, which is why serious practitioners essentially never bet full Kelly. At
    half Kelly it is fraction**3, so the same drawdown is 12.5%.

    This assumes exposure is CONTINUOUSLY rescaled to the current bankroll. A
    player grinding one fixed stake is described by `ruin.drawdown_probability`
    instead. Real poker sits between the two: you rescale, but in discrete jumps
    when you change stake.

    Defined for 0 < k < 2, the range over which the exponent stays positive. At
    k >= 2 growth is already zero or negative and every drawdown becomes certain,
    so the formula has nothing left to say and the call is rejected.
    """
    if not 0.0 < fraction < 1.0:
        raise ValueError(f"fraction must be in (0, 1), got {fraction}")
    if not 0.0 < kelly_fraction < 2.0:
        raise ValueError(f"kelly_fraction must be in (0, 2), got {kelly_fraction}")
    return fraction ** (2.0 / kelly_fraction - 1.0)
