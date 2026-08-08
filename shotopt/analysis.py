"""Assembling the per-stake answer from a config.

This is the only module that knows about both `Config` and the maths. The maths
modules stay free of config objects so a later simulation can import them
directly; the CLI and the charts both consume `StakeReport` objects from here, so
the numbers on a chart and the numbers in the table can never drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import estimation, kelly, rates, ruin
from .config import Config, Stake

__all__ = ["StakeReport", "build_reports", "best_affordable"]


@dataclass(frozen=True)
class StakeReport:
    """Everything the tool has to say about one stake, at one bankroll."""

    stake: Stake
    winrate_eff: float
    """Win rate after the multi-tabling haircut, bb/100."""
    stdev_eff: float
    """Standard deviation after the table-correlation inflation, bb/100."""
    bankroll_bb: float
    buyins: float
    eur_per_hour: float
    risk_of_ruin: float
    within_tolerance: bool
    drawdown_50: float
    """P(ever losing half the roll) at this fixed stake."""

    # None wherever a non-positive effective win rate makes the quantity undefined.
    bankroll_for_tolerance_eur: float | None
    kelly_bankroll_eur: float | None
    supported_bb_eur: float | None
    """The big blind this bankroll supports at the configured Kelly fraction."""

    # None unless the stake declared `hands`.
    winrate_ci: tuple[float, float] | None
    shaded_winrate: float | None
    shaded_kelly_bankroll_eur: float | None

    @property
    def buyins_for_tolerance(self) -> float | None:
        if self.bankroll_for_tolerance_eur is None:
            return None
        return self.bankroll_for_tolerance_eur / self.stake.buyin_eur

    @property
    def kelly_buyins(self) -> float | None:
        if self.kelly_bankroll_eur is None:
            return None
        return self.kelly_bankroll_eur / self.stake.buyin_eur


def _report_for(stake: Stake, config: Config) -> StakeReport:
    winrate_eff = rates.total_winrate(
        stake.winrate_bb100,
        config.tables,
        config.winrate_haircut_bb_per_table,
        stake.rake_bb100,
        config.rakeback_pct,
    )
    stdev_eff = ruin.effective_stdev(
        stake.stdev_bb100, config.tables, config.table_correlation
    )
    bankroll_bb = stake.bankroll_bb(config.bankroll_eur)

    current_ruin = ruin.risk_of_ruin(winrate_eff, stdev_eff, bankroll_bb)
    drawdown_50 = ruin.drawdown_probability(winrate_eff, stdev_eff, bankroll_bb, 0.5)

    # A losing stake has no finite safe bankroll and no Kelly size; those columns
    # are left empty rather than filled with a misleading large number.
    if winrate_eff > 0:
        tolerance_bb = ruin.bankroll_for_ruin(winrate_eff, stdev_eff, config.ruin_tolerance)
        bankroll_for_tolerance_eur = tolerance_bb * stake.bb_eur
        kelly_bb = kelly.required_bankroll_bb(winrate_eff, stdev_eff, config.kelly_fraction)
        kelly_bankroll_eur = kelly_bb * stake.bb_eur
        supported_bb_eur = kelly.optimal_bb_eur(
            config.bankroll_eur, winrate_eff, stdev_eff, config.kelly_fraction
        )
    else:
        bankroll_for_tolerance_eur = None
        kelly_bankroll_eur = None
        supported_bb_eur = None

    if stake.hands is not None:
        ci = estimation.winrate_ci(winrate_eff, stdev_eff, stake.hands)
        shaded = estimation.shaded_winrate(winrate_eff, stdev_eff, stake.hands)
        shaded_kelly_eur = (
            kelly.required_bankroll_bb(shaded, stdev_eff, config.kelly_fraction)
            * stake.bb_eur
            if shaded > 0
            else None
        )
    else:
        ci = None
        shaded = None
        shaded_kelly_eur = None

    return StakeReport(
        stake=stake,
        winrate_eff=winrate_eff,
        stdev_eff=stdev_eff,
        bankroll_bb=bankroll_bb,
        buyins=config.bankroll_eur / stake.buyin_eur,
        eur_per_hour=rates.eur_per_hour(
            winrate_eff, stake.bb_eur, config.tables, config.hands_per_hour_per_table
        ),
        risk_of_ruin=current_ruin,
        within_tolerance=current_ruin <= config.ruin_tolerance,
        drawdown_50=drawdown_50,
        bankroll_for_tolerance_eur=bankroll_for_tolerance_eur,
        kelly_bankroll_eur=kelly_bankroll_eur,
        supported_bb_eur=supported_bb_eur,
        winrate_ci=ci,
        shaded_winrate=shaded,
        shaded_kelly_bankroll_eur=shaded_kelly_eur,
    )


def build_reports(config: Config) -> list[StakeReport]:
    """One report per configured stake, ordered by stake size ascending."""
    reports = [_report_for(stake, config) for stake in config.stakes]
    return sorted(reports, key=lambda r: r.stake.bb_eur)


def best_affordable(reports: list[StakeReport]) -> StakeReport | None:
    """The decision rule in one line: highest EUR/hour that stays inside tolerance.

    Returns None when no configured stake clears the tolerance at this bankroll,
    which is itself the answer - play smaller than anything listed, or accept a
    higher risk of ruin.
    """
    affordable = [r for r in reports if r.within_tolerance and r.eur_per_hour > 0]
    if not affordable:
        return None
    return max(affordable, key=lambda r: r.eur_per_hour)
