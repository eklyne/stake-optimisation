"""CSV copies of the two tables the terminal prints.

Same numbers, unrounded, in a shape you can pivot. The frontier gets one column
PER STAKE holding the table count, not just the "10x 100NL + 2x 200NL" label -
a label is unusable as a spreadsheet dimension, and the counts are what you would
want to chart or filter on.

Money columns are written in the DISPLAY currency and carry its code in their
header (`per_hour_gbp`), so a column can never be read in the wrong unit. bb/100
columns and the stake's own `bb_eur` are untouched - a big blind is a property of
the table, not of how you are reading the report.
"""

from __future__ import annotations

import csv
from pathlib import Path

from . import rates
from .config import Config
from .mix import Allocation, StakeScreen
from .money import Currency

__all__ = ["write_stake_screen", "write_frontier", "write_tables"]


def write_stake_screen(
    screens: list[StakeScreen],
    path: Path,
    rakeback_pct: float = 0.0,
    currency: Currency | None = None,
) -> Path:
    """One row per configured stake, including the ruled-out ones."""
    from .money import EUR

    currency = currency or EUR
    suffix = currency.code.lower()
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "stake",
                "bb_eur",
                "winrate_bb100",
                "rake_bb100",
                "rakeback_bb100",
                "net_winrate_bb100",
                "stdev_bb100",
                "hands",
                "max_tables",
                f"mean_per_100_{suffix}",
                f"stdev_per_100_{suffix}",
                f"per_hour_{suffix}",
                "kept",
                "excluded_reason",
                "dominated_by",
            ]
        )
        for screen in screens:
            stake = screen.stake
            rakeback = rates.rakeback_bb100(stake.rake_bb100, rakeback_pct)
            writer.writerow(
                [
                    stake.name,
                    stake.bb_eur,
                    stake.winrate_bb100,
                    stake.rake_bb100 if stake.rake_bb100 is not None else "",
                    round(rakeback, 4),
                    round(screen.mean_eur_per_100 / stake.bb_eur, 4),
                    stake.stdev_bb100,
                    stake.hands if stake.hands is not None else "",
                    stake.max_tables if stake.max_tables is not None else "",
                    round(currency.from_eur(screen.mean_eur_per_100), 4),
                    round(currency.from_eur(screen.stdev_eur_per_100), 4),
                    round(currency.from_eur(screen.eur_per_hour), 4),
                    int(screen.kept),
                    screen.excluded_reason or "",
                    screen.dominated_by.name if screen.dominated_by else "",
                ]
            )
    return path


def write_frontier(
    frontier: list[Allocation], config: Config, best: Allocation | None, path: Path
) -> Path:
    """One row per undominated mix, with a table-count column per stake.

    `within_ruin_tolerance` is the analytic verdict and is written whichever mode
    is active - it is cheap and it is the column most people will filter on.
    `risk_mode` records which rule actually chose `is_best`, so a row flagged
    inside ruin tolerance but not chosen is explicable from the file alone.

    The downswing measure is deliberately NOT a column here: it costs a
    simulation per row, and this file is written on every run including the ones
    that never build a chart. It is on the downswing frontier chart instead.
    """
    currency = config.currency
    suffix = currency.code.lower()
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [f"per_hour_{suffix}", "risk_of_ruin", "p_drawdown_50",
             "within_ruin_tolerance", "is_best", "risk_mode",
             f"loss_below_start_median_{suffix}",
             f"loss_below_start_p90_{suffix}",
             f"loss_below_start_p99_{suffix}"]
            + [f"tables_{stake.name}" for stake in config.stakes]
            + ["mix"]
        )
        for allocation in frontier:
            writer.writerow(
                [
                    round(currency.from_eur(allocation.eur_per_hour), 4),
                    allocation.risk_of_ruin,
                    allocation.drawdown_50,
                    int(allocation.within_ruin_tolerance),
                    int(best is not None and allocation.counts == best.counts),
                    config.risk_mode,
                ]
                + [
                    round(currency.from_eur(allocation.loss_below_start(q)), 2)
                    if allocation.loss_below_start(q) is not None
                    else ""
                    for q in (0.50, 0.90, 0.99)
                ]
                + list(allocation.counts)
                + [allocation.label]
            )
    return path


def write_tables(
    screens: list[StakeScreen],
    frontier: list[Allocation],
    config: Config,
    best: Allocation | None,
    directory: Path,
) -> list[Path]:
    """Write both CSVs into `directory`, returning the paths written."""
    directory.mkdir(parents=True, exist_ok=True)
    return [
        write_stake_screen(
            screens, directory / "stake_screen.csv", config.rakeback_pct, config.currency
        ),
        write_frontier(frontier, config, best, directory / "frontier.csv"),
    ]
