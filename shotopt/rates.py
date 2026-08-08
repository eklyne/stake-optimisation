"""Turning a bb/100 win rate into money per hour.

Rate conversion is not an afterthought here - it is half the decision. Stake
selection reduces to two covariates, expected value and risk of ruin, and the EV
one has to be computed in EUR/hour rather than bb/100. bb/100 is deliberately
blind to stake size, which is precisely the thing being chosen.

Table count enters the EV side twice: it multiplies volume, and it may degrade
the win rate. Only the first is certain.
"""

from __future__ import annotations

__all__ = [
    "effective_winrate",
    "rakeback_bb100",
    "total_winrate",
    "hands_per_hour",
    "eur_per_hour",
]


def effective_winrate(
    winrate: float, tables: int, haircut_bb_per_table: float = 0.0
) -> float:
    """Win rate after the multi-tabling penalty, in bb/100.

        mu_eff = mu - haircut * (tables - 1)

    Attention is finite, so playing more tables plausibly costs win rate; the
    first table is free and each additional one is charged. Whether the effect is
    real, and how big, is an open question this repo has NOT measured - so the
    haircut defaults to 0.0 and any penalty is an assumption the user typed in,
    not a finding.
    """
    if tables < 1:
        raise ValueError(f"tables must be at least 1, got {tables}")
    if haircut_bb_per_table < 0:
        raise ValueError(f"haircut must be non-negative, got {haircut_bb_per_table}")
    return winrate - haircut_bb_per_table * (tables - 1)


def rakeback_bb100(rake_bb100: float | None, rakeback_pct: float) -> float:
    """Rakeback earned per 100 hands, in bb.

    A rebate on rake already paid, so it is additional to a win rate that is
    already net of rake - which is what a tracker reports. No double counting.

    The important property is that it carries NO VARIANCE. It is a rebate on
    volume, not a gamble, so it lifts the mean and leaves the standard deviation
    exactly where it was - improving the mean/variance ratio the ruin calculation
    runs on, and doing so hardest at the stakes where rake is largest in bb terms.
    """
    if rake_bb100 is None:
        return 0.0
    if rake_bb100 < 0:
        raise ValueError(f"rake must be non-negative, got {rake_bb100}")
    if not 0.0 <= rakeback_pct <= 1.0:
        raise ValueError(f"rakeback_pct must be in [0, 1], got {rakeback_pct}")
    return rake_bb100 * rakeback_pct


def total_winrate(
    winrate_bb100: float,
    tables: int,
    haircut_bb_per_table: float = 0.0,
    rake_bb100: float | None = None,
    rakeback_pct: float = 0.0,
) -> float:
    """Win rate actually banked, bb/100: table haircut off, rakeback on.

    The one place the two adjustments are combined, so no caller can apply one
    and forget the other.
    """
    return effective_winrate(winrate_bb100, tables, haircut_bb_per_table) + rakeback_bb100(
        rake_bb100, rakeback_pct
    )


def hands_per_hour(tables: int, hands_per_hour_per_table: float) -> float:
    """Total hands dealt per hour across all tables."""
    if tables < 1:
        raise ValueError(f"tables must be at least 1, got {tables}")
    if hands_per_hour_per_table <= 0:
        raise ValueError(
            f"hands_per_hour_per_table must be positive, got {hands_per_hour_per_table}"
        )
    return tables * hands_per_hour_per_table


def eur_per_hour(
    winrate: float, bb_eur: float, tables: int, hands_per_hour_per_table: float
) -> float:
    """EUR/hour from a bb/100 win rate.

    Pass an ALREADY-haircut win rate if you want the multi-tabling penalty
    counted - this function only handles the volume side, so that the two effects
    of table count stay visibly separate.
    """
    if bb_eur <= 0:
        raise ValueError(f"bb_eur must be positive, got {bb_eur}")
    return (winrate / 100.0) * bb_eur * hands_per_hour(tables, hands_per_hour_per_table)
