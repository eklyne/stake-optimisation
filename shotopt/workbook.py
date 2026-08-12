"""The deck's numbers, as a spreadsheet.

Every figure on a slide comes from somewhere, and a slide is a terrible place to
interrogate it from: you cannot sort a chart, filter a footnote, or check what the
mix one rung over would have done. This writes the same numbers into tabs you can
pivot - the pptx and the xlsx are a pair, built in the same run from the same
objects, so they cannot disagree.

Written from the values the deck has ALREADY computed, not recomputed from the
config. Recomputing would mean re-running the tolerance walk (a minute or two) and
re-simulating every mix, and any drift between the two passes would show up as a
spreadsheet that quietly contradicts the deck it shipped with.

Money columns are in the display currency and carry its code in the header
(`per_hour_gbp`), exactly as the CSVs do. bb/100 columns are never converted.

`xlsxwriter` rather than pandas: this package hand-rolls its CSVs with the stdlib
and has no dataframe anywhere else, so a dataframe dependency for one output would
be the heaviest thing in the repo.
"""

from __future__ import annotations

from pathlib import Path

from . import rates, sim
from .config import Config

__all__ = ["write", "SHEETS"]

SHEETS = (
    ("INDEX", "What is on each tab"),
    ("RUN", "Every input this run used, including the CLI overrides"),
    ("STAKES", "One row per stake: the config inputs and the screen verdict"),
    ("ALLOCATIONS", "Every possible mix, scored - the frontier chart's full cloud"),
    ("FRONTIER", "The undominated mixes, in the order the terminal prints them"),
    ("DOWNSWING", "Simulated peak-to-trough falls, for the mixes the deck quotes"),
    ("LADDER", "The optimum re-solved at each bankroll growth step"),
    ("STEP_UP", "The two ways to move one table up, and what each costs"),
    ("SIM_FAN", "Bankroll percentile bands over the horizon, per headline mix"),
    ("SIM_OUTCOMES", "Where the headline mixes finish, and how deep they dig"),
    ("WINRATE_CI", "The win-rate slide: modelled rate, rakeback, sample interval"),
)


def _sheet(book, name, headers, rows, formats):
    """One tab, with a frozen bold header row and columns wide enough to read."""
    sheet = book.add_worksheet(name)
    sheet.freeze_panes(1, 0)
    for column, header in enumerate(headers):
        sheet.write(0, column, header, formats["header"])
        # Wide enough for the header itself, or for the values, whichever is more.
        longest = max(
            [len(str(header))] + [len(str(row[column])) for row in rows[:400]]
        )
        sheet.set_column(column, column, min(max(longest + 2, 9), 42))
    for index, row in enumerate(rows, start=1):
        for column, value in enumerate(row):
            sheet.write(index, column, value)
    if rows:
        sheet.autofilter(0, 0, len(rows), len(headers) - 1)
    return sheet


def write(
    path: Path,
    config: Config,
    screens,
    allocations,
    edge,
    best,
    current,
    simulations,
    ladder,
    step_ups,
) -> Path:
    """Write the workbook. Every argument is a value the deck already holds."""
    import xlsxwriter

    money = config.currency.from_eur
    code = config.currency.code.lower()
    names = [stake.name for stake in config.stakes]

    book = xlsxwriter.Workbook(str(path), {"nan_inf_to_errors": True})
    formats = {"header": book.add_format({"bold": True, "bg_color": "#DDDDDD"})}

    # ---- INDEX ------------------------------------------------------------- #
    _sheet(
        book, "INDEX", ["tab", "what it holds"],
        [[name, description] for name, description in SHEETS if name != "INDEX"],
        formats,
    )

    # ---- RUN --------------------------------------------------------------- #
    # The values ACTUALLY used, so a run with `--bankroll 60000` documents itself
    # rather than pointing at a config file that says something else.
    downswing = (
        f"{config.downswing_probability:.0%} chance of "
        f"{config.currency.fmt(config.downswing_amount_eur)} in "
        f"{config.downswing_hands:,} hands"
        if config.downswing_amount_eur is not None else "not set"
    )
    _sheet(
        book, "RUN", ["setting", "value"],
        [
            ["bankroll", money(config.bankroll_eur)],
            ["currency", config.currency.code],
            ["fx (EUR per unit)", config.currency.eur_per_unit],
            ["tables", config.tables],
            ["risk mode", config.risk_mode],
            ["ruin tolerance", config.ruin_tolerance],
            ["downswing tolerance", downswing],
            ["rakeback", config.rakeback_pct],
            ["hands/hour/table", config.hands_per_hour_per_table],
            ["hands/hour total", config.tables * config.hands_per_hour_per_table],
            ["simulation horizon (hands)", config.timescale_hands],
            ["simulated lifetimes", config.sim_paths],
            ["win-rate haircut per table", config.winrate_haircut_bb_per_table],
            ["table correlation", config.table_correlation],
            ["Kelly fraction (report/stake only)", config.kelly_fraction],
        ],
        formats,
    )

    # ---- STAKES ------------------------------------------------------------ #
    _sheet(
        book, "STAKES",
        ["stake", "bb_eur", "winrate_bb100", "measured_winrate_bb100", "stdev_bb100",
         "rake_bb100", "rakeback_bb100", "banked_bb100", "sample_hands",
         "current_hands", "max_tables", f"mean_per_100_{code}", f"stdev_per_100_{code}",
         f"per_hour_{code}", f"on_tables_{code}", "kept", "excluded_reason"],
        [
            [
                s.stake.name, s.stake.bb_eur, s.stake.winrate_bb100,
                s.stake.measured_winrate_bb100 if s.stake.measured_winrate_bb100 is not None else "",
                s.stake.stdev_bb100,
                s.stake.rake_bb100 if s.stake.rake_bb100 is not None else "",
                rates.rakeback_bb100(s.stake.rake_bb100, config.rakeback_pct),
                s.mean_eur_per_100 / s.stake.bb_eur,
                s.stake.hands if s.stake.hands is not None else "",
                s.stake.current_hands if s.stake.current_hands is not None else "",
                s.stake.max_tables if s.stake.max_tables is not None else "",
                money(s.mean_eur_per_100), money(s.stdev_eur_per_100),
                money(s.eur_per_hour), money(s.exposure_eur),
                int(s.kept), s.excluded_reason or "",
            ]
            for s in screens
        ],
        formats,
    )

    # ---- ALLOCATIONS ------------------------------------------------------- #
    # The whole cloud, flagged - so "what would 8x 200NL + 4x 400NL have done"
    # is a filter rather than a re-run.
    on_edge = {a.counts for a in edge}
    _sheet(
        book, "ALLOCATIONS",
        [f"tables_{name}" for name in names]
        + ["mix", f"per_hour_{code}", f"on_tables_{code}", f"mean_per_100_{code}",
           f"stdev_per_100_{code}",
           "risk_of_ruin", "ruin_odds_against", "p_lose_half",
           "within_ruin_tolerance", "on_frontier", "is_best", "is_current"],
        [
            list(a.counts) + [
                a.label, money(a.eur_per_hour), money(a.exposure_eur),
                money(a.mean_eur_per_100),
                money(a.stdev_eur_per_100), a.risk_of_ruin,
                (1.0 / a.risk_of_ruin) if a.risk_of_ruin > 0 else "",
                a.drawdown_50,
                int(a.within_ruin_tolerance), int(a.counts in on_edge),
                int(best is not None and a.counts == best.counts),
                int(current is not None and a.counts == current.counts),
            ]
            for a in allocations
        ],
        formats,
    )

    # ---- FRONTIER ---------------------------------------------------------- #
    _sheet(
        book, "FRONTIER",
        [f"tables_{name}" for name in names]
        + ["mix", f"per_hour_{code}", f"on_tables_{code}", "risk_of_ruin",
           "ruin_odds_against", "p_lose_half", "within_ruin_tolerance", "is_best",
           f"loss_below_start_p50_{code}", f"loss_below_start_p90_{code}",
           f"loss_below_start_p99_{code}"],
        [
            list(a.counts) + [
                a.label, money(a.eur_per_hour), money(a.exposure_eur),
                a.risk_of_ruin,
                (1.0 / a.risk_of_ruin) if a.risk_of_ruin > 0 else "",
                a.drawdown_50,
                int(a.within_ruin_tolerance),
                int(best is not None and a.counts == best.counts),
            ] + [
                money(a.loss_below_start(q)) if a.loss_below_start(q) is not None else ""
                for q in (0.50, 0.90, 0.99)
            ]
            for a in edge
        ],
        formats,
    )

    # ---- DOWNSWING --------------------------------------------------------- #
    # Only mixes the deck already simulated: every call here is a cache hit, so
    # the workbook adds no simulation time to the run.
    quoted = list(
        {
            a.counts: a
            for a in list(edge) + [a for a in (best, current) if a is not None]
        }.values()
    )
    _sheet(
        book, "DOWNSWING",
        ["mix", f"on_tables_{code}", "horizon_hands", "simulated_lifetimes",
         f"median_worst_fall_{code}", f"p90_worst_fall_{code}",
         f"p99_worst_fall_{code}", f"worst_seen_{code}", "ruin_within_horizon"],
        [
            [
                a.label, money(a.exposure_eur), config.timescale_hands,
                sim.TABLE_PATHS,
                money(swing["median"]), money(swing["p90"]), money(swing["p99"]),
                money(swing["max"]), swing["ruin"],
            ]
            for a, swing in (
                (a, sim.expected_drawdown(config, a, config.timescale_hands))
                for a in quoted
            )
        ],
        formats,
    )

    # ---- LADDER ------------------------------------------------------------ #
    _sheet(
        book, "LADDER",
        ["step", f"bankroll_{code}", "optimal_mix", f"per_hour_{code}",
         f"on_tables_{code}", "risk_of_ruin", f"median_worst_fall_{code}",
         f"p90_worst_fall_{code}", f"p99_worst_fall_{code}"],
        [
            [label, money(bankroll),
             allocation.label if allocation else "nothing clears tolerance",
             money(allocation.eur_per_hour) if allocation else "",
             money(allocation.exposure_eur) if allocation else "",
             allocation.risk_of_ruin if allocation else "",
             *(
                 [money(swing["median"]), money(swing["p90"]), money(swing["p99"])]
                 if allocation is not None else ["", "", ""]
             )]
            for label, bankroll, scenario, allocation in ladder
            for swing in [
                sim.expected_drawdown(scenario, allocation, config.timescale_hands)
                if allocation is not None else {}
            ]
        ],
        formats,
    )

    # ---- STEP_UP ----------------------------------------------------------- #
    _sheet(
        book, "STEP_UP",
        ["move", "mix", f"per_hour_{code}", f"per_hour_delta_{code}",
         f"on_tables_{code}", "risk_of_ruin", "ruin_multiple_vs_optimal",
         "within_tolerance"],
        [
            [o.label, o.allocation.label, money(o.allocation.eur_per_hour),
             money(o.eur_per_hour_delta), money(o.allocation.exposure_eur),
             o.allocation.risk_of_ruin,
             o.ruin_multiple, int(o.within_tolerance)]
            for o in step_ups
        ],
        formats,
    )

    # ---- SIM_FAN / SIM_OUTCOMES -------------------------------------------- #
    import numpy as np

    fan_rows, outcome_rows = [], []
    for counts, result in simulations.items():
        label = result.allocation.label
        for index, hands in enumerate(result.checkpoint_hands):
            column = result.checkpoint_bankroll[:, index]
            fan_rows.append([
                label, int(hands),
                *(money(float(np.percentile(column, p))) for p in (5, 25, 50, 75, 95)),
            ])
        outcome_rows.append([
            label, result.hands, result.paths, result.ruin_probability,
            *(money(float(np.percentile(result.final_bankroll, p)))
              for p in (5, 25, 50, 75, 95)),
            *(money(float(np.percentile(result.max_drawdown, p)))
              for p in (50, 90, 99)),
        ])

    _sheet(
        book, "SIM_FAN",
        ["mix", "hands", f"p5_{code}", f"p25_{code}", f"p50_{code}",
         f"p75_{code}", f"p95_{code}"],
        fan_rows, formats,
    )
    _sheet(
        book, "SIM_OUTCOMES",
        ["mix", "horizon_hands", "lifetimes", "ruin_within_horizon",
         f"final_p5_{code}", f"final_p25_{code}", f"final_p50_{code}",
         f"final_p75_{code}", f"final_p95_{code}",
         f"worst_fall_p50_{code}", f"worst_fall_p90_{code}",
         f"worst_fall_p99_{code}"],
        outcome_rows, formats,
    )

    # ---- WINRATE_CI -------------------------------------------------------- #
    from . import estimation

    hours_per_100 = config.tables * config.hands_per_hour_per_table / 100.0
    ci_rows = []
    for screen in screens:
        stake = screen.stake
        back = rates.rakeback_bb100(stake.rake_bb100, config.rakeback_pct)
        assumed = stake.measured_winrate_bb100 is not None
        half = (
            estimation.Z_95 * estimation.winrate_stderr(stake.stdev_bb100, stake.hands)
            if stake.hands else None
        )
        measured = stake.measured_winrate_bb100 if assumed else stake.winrate_bb100
        ci_rows.append([
            stake.name, stake.winrate_bb100, back, stake.winrate_bb100 + back,
            "assumed" if assumed else "measured",
            measured if stake.hands else "",
            stake.hands if stake.hands else "",
            half if half is not None else "",
            (measured - half) if half is not None else "",
            (measured + half) if half is not None else "",
            money((stake.winrate_bb100 + back) * stake.bb_eur * hours_per_100),
        ])
    _sheet(
        book, "WINRATE_CI",
        ["stake", "modelled_winrate_bb100", "rakeback_bb100", "banked_bb100",
         "winrate_is", "measured_winrate_bb100", "sample_hands",
         "ci_half_width_bb100", "ci_low_bb100", "ci_high_bb100",
         f"banked_per_hour_{code}"],
        ci_rows, formats,
    )

    book.close()
    return path
