"""CSV copies of the two tables the terminal prints.

Same numbers, unrounded, in a shape you can pivot. The frontier gets one column
PER STAKE holding the table count, not just the "10x 100NL + 2x 200NL" label -
a label is unusable as a spreadsheet dimension, and the counts are what you would
want to chart or filter on.
"""

from __future__ import annotations

import csv
from pathlib import Path

from . import rates
from .config import Config
from .mix import Allocation, StakeScreen

__all__ = ["write_stake_screen", "write_frontier", "write_tables"]


def write_stake_screen(
    screens: list[StakeScreen], path: Path, rakeback_pct: float = 0.0
) -> Path:
    """One row per configured stake, including the ruled-out ones."""
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
                "mean_eur_per_100",
                "stdev_eur_per_100",
                "eur_per_hour",
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
                    round(screen.mean_eur_per_100, 4),
                    round(screen.stdev_eur_per_100, 4),
                    round(screen.eur_per_hour, 4),
                    int(screen.kept),
                    screen.excluded_reason or "",
                    screen.dominated_by.name if screen.dominated_by else "",
                ]
            )
    return path


def write_frontier(
    frontier: list[Allocation], config: Config, best: Allocation | None, path: Path
) -> Path:
    """One row per undominated mix, with a table-count column per stake."""
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["eur_per_hour", "risk_of_ruin", "p_drawdown_50", "within_tolerance", "is_best",
             "loss_below_start_median", "loss_below_start_p90", "loss_below_start_p99"]
            + [f"tables_{stake.name}" for stake in config.stakes]
            + ["mix"]
        )
        for allocation in frontier:
            writer.writerow(
                [
                    round(allocation.eur_per_hour, 4),
                    allocation.risk_of_ruin,
                    allocation.drawdown_50,
                    int(allocation.within_tolerance),
                    int(best is not None and allocation.counts == best.counts),
                ]
                + [
                    round(allocation.loss_below_start(q), 2)
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
        write_stake_screen(screens, directory / "stake_screen.csv", config.rakeback_pct),
        write_frontier(frontier, config, best, directory / "frontier.csv"),
    ]
