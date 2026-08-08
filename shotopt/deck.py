"""The deck, in three sections.

**1. Optimal stake distribution** - which stakes are worth playing and in what
proportion: the stake screen, the bb and euro waterfalls, the frontier, the
optimum with its nearest alternatives, and a simulation of it.

**2. Shot-taking** - the two moves up from the optimum (reach at the top,
consolidate at the bottom) and what each costs in risk.

**3. Current configuration** - the mix actually played, reconstructed from hands
per stake, priced against the optimum and simulated the same way.

Then a methodology appendix.

Each section's simulation sits in the section whose mix it simulates, so the
optimum and the real allocation are never compared across a section break.

Every number is recomputed here from the same functions the CLI prints, so a
slide cannot disagree with the terminal. Nothing is hardcoded.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from pptx.util import Inches, Pt  # noqa: E402

from . import charts, estimation, mix, pptx_common as pc, progress, rates, sim  # noqa: E402
from .config import Config  # noqa: E402

__all__ = ["build"]

# Waterfall colours: money in, money out, and the two totals.
COL_POSITIVE = "#1baf7a"
COL_NEGATIVE = "#d03b3b"
COL_TOTAL = "#2a78d6"
COL_INK = "#0b0b0b"
COL_MUTED = "#7a7972"

def drawdown_note(config: Config) -> str:
    """Defined once and repeated under every table carrying the columns - a
    reader landing on one slide should not have to hunt for what they mean."""
    hands = config.timescale_hands
    hours = hands / (config.tables * config.hands_per_hour_per_table)
    paths = sim.TABLE_PATHS
    return (
        f"HOW THE DOWNSWING COLUMNS ARE CALCULATED.  (1) Simulate one lifetime: {hands:,} "
        f"hands ({hours:,.0f} hours at {config.tables} tables) played at that exact mix. "
        f"(2) Within that lifetime find the single deepest PEAK-TO-TROUGH fall - how far the "
        f"bankroll dropped below whatever high it had previously reached. That is one number "
        f"per lifetime. (3) Repeat for {paths:,} independent lifetimes. (4) MEDIAN WORST "
        f"DOWNSWING is the middle of those {paths:,} numbers: in half of lifetimes the worst "
        f"fall is shallower than this, in half it is deeper. 1% WORST DOWNSWING is the 99th "
        f"percentile: one lifetime in a hundred is worse.  Note this is NOT the median of "
        f"every downswing you have - most of those are trivial and there are thousands of "
        f"them. It is the median of the WORST one per lifetime. The timescale is part of the "
        f"number: given unlimited time a peak-to-trough fall grows without bound, because a "
        f"winning bankroll keeps making new highs to fall from. Change the timescale and "
        f"these change with it."
    )


# --------------------------------------------------------------------------- #
# Slide 1 - the stake table
# --------------------------------------------------------------------------- #
def _stake_table_slide(prs, layouts, config: Config, screens: list[mix.StakeScreen]):
    slide = prs.slides.add_slide(layouts["Title and Content"])
    pc.add_title(slide, "Every stake, priced on its own")

    columns = [
        ("Stake", 0.85),
        ("Hands", 0.95),
        ("Win rate\nbb/100", 0.95),
        ("Rake\nbb/100", 0.85),
        ("Rakeback\nbb/100", 0.95),
        ("Banked\nbb/100", 0.95),
        ("+/- 95%\nbb/100", 0.90),
        ("Banked\nEUR/100", 0.95),
        ("SD\nEUR/100", 0.90),
        ("EUR/hr", 0.85),
        ("Verdict", 3.20),
    ]
    rows = len(screens) + 1
    table_width = Inches(sum(w for _, w in columns))
    left = int(pc.CONTENT_LEFT + (pc.CONTENT_WIDTH - table_width) / 2)
    shape = slide.shapes.add_table(
        rows, len(columns), left, pc.CONTENT_TOP + Inches(0.35),
        table_width, Inches(0.4 + 0.32 * len(screens)),
    )
    table = shape.table
    for index, (_, width) in enumerate(columns):
        table.columns[index].width = Inches(width)

    for index, (label, _) in enumerate(columns):
        cell = table.cell(0, index)
        pc._zero_cell_margins(cell)
        pc.set_cell(cell, label, font_size=9, bold=True,
                    bg_colour=pc.TABLE_HEADER_BG, font_colour=pc.WHITE, wrap=True)

    for row, screen in enumerate(screens, start=1):
        stake = screen.stake
        rakeback = rates.rakeback_bb100(stake.rake_bb100, config.rakeback_pct)
        banked_bb = screen.mean_eur_per_100 / stake.bb_eur
        margin = (
            f"{estimation.winrate_ci(0.0, stake.stdev_bb100, stake.hands)[1]:.1f}"
            if stake.hands else "-"
        )
        # Excluded rows are greyed wholesale rather than flagged in one column:
        # the point is that none of their numbers feed the answer.
        excluded = not screen.kept
        ink = pc.GRID_GREY if excluded else pc.BLACK
        values = [
            stake.name,
            f"{stake.hands:,}" if stake.hands else "-",
            f"{stake.winrate_bb100:.2f}",
            f"-{stake.rake_bb100:.2f}" if stake.rake_bb100 else "-",
            f"+{rakeback:.2f}" if rakeback else "-",
            f"{banked_bb:.2f}",
            f"+/-{margin}",
            f"{screen.mean_eur_per_100:.2f}",
            f"{screen.stdev_eur_per_100:.0f}",
            f"{screen.eur_per_hour:,.0f}",
            "in the mix" if screen.kept else screen.excluded_reason,
        ]
        for index, value in enumerate(values):
            cell = table.cell(row, index)
            pc._zero_cell_margins(cell)
            pc.set_cell(
                cell, value, font_size=9, bold=(index == 0),
                bg_colour=pc.TABLE_LABEL_BG if excluded else None,
                font_colour=pc.COL_TEXT_RED if (excluded and index == 10) else ink,
            )

    _footnote(
        slide,
        "Win rate is net of rake, as the tracker reports it; rake and rakeback are shown "
        "separately so the composition is visible. Rakeback at "
        f"{config.rakeback_pct:.0%}. The +/- column is the 95% interval half-width implied "
        "by the sample - a win rate with no volume behind it is a guess, not a measurement.",
    )
    return slide


# --------------------------------------------------------------------------- #
# Slides 2 and 3 - the waterfalls
# --------------------------------------------------------------------------- #
def _waterfall_figure(screens, config: Config, in_euros: bool):
    """One waterfall panel per kept stake, sharing a y axis.

    Bars: win rate before rake -> rake paid -> rakeback -> banked. Sharing the
    axis is the whole point of the slide; per-panel scaling would hide that the
    bars shrink in bb terms and grow in euros as the stakes rise.
    """
    kept = [s for s in screens if s.kept]
    charts._style()

    series = []
    for screen in kept:
        stake = screen.stake
        rake = stake.rake_bb100 or 0.0
        rakeback = rates.rakeback_bb100(stake.rake_bb100, config.rakeback_pct)
        before = stake.winrate_bb100 + rake
        banked = screen.mean_eur_per_100 / stake.bb_eur
        scale = stake.bb_eur if in_euros else 1.0
        series.append(
            (stake.name, before * scale, -rake * scale, rakeback * scale, banked * scale)
        )

    # The tallest thing on any panel is the opening or closing bar; the rake bar
    # hangs DOWN from the opening one, so it never sets the ceiling. (Its stored
    # height is already negative - adding it here once cost a third of the axis
    # to dead space.)
    y_max = max(max(before, banked) for _, before, _, _, banked in series) * 1.16
    y_min = min(0.0, min(banked for *_, banked in series)) * 1.1

    fig, axes = plt.subplots(
        1, len(series), figsize=(3.05 * len(series), 4.6), sharey=True, squeeze=False
    )
    unit = "EUR / 100 hands" if in_euros else "bb / 100 hands"

    for ax, (name, before, rake, rakeback, banked) in zip(axes[0], series):
        after_rake = before + rake
        steps = [
            ("Before\nrake", 0.0, before, COL_TOTAL),
            ("Rake", after_rake, -rake, COL_NEGATIVE),
            ("Rakeback", after_rake, rakeback, COL_POSITIVE),
            ("Banked", 0.0, banked, COL_TOTAL),
        ]
        for position, (label, bottom, height, colour) in enumerate(steps):
            ax.bar(position, height, bottom=bottom, color=colour, width=0.62,
                   edgecolor=charts.SURFACE, linewidth=1.5)
            value = before if position == 0 else (rake if position == 1 else
                                                  rakeback if position == 2 else banked)
            sign = "" if position in (0, 3) else ("-" if position == 1 else "+")
            ax.annotate(
                f"{sign}{abs(value):,.2f}" if not in_euros else f"{sign}{abs(value):,.1f}",
                xy=(position, bottom + height),
                xytext=(0, 4), textcoords="offset points",
                ha="center", fontsize=8.5, color=COL_INK, fontweight="bold",
            )
        # Connectors, so the eye follows the running total across the bars.
        ax.plot([0.31, 0.69], [before, before], color=COL_MUTED, linewidth=0.9, linestyle=":")
        ax.plot([1.31, 1.69], [after_rake, after_rake], color=COL_MUTED,
                linewidth=0.9, linestyle=":")
        ax.plot([2.31, 2.69], [banked, banked], color=COL_MUTED, linewidth=0.9, linestyle=":")

        ax.set_xticks(range(4), [s[0] for s in steps], fontsize=8.5)
        ax.axhline(0, color=COL_MUTED, linewidth=1.0)
        ax.set_title(name, fontsize=11, pad=8)
        ax.grid(axis="y", alpha=0.9)
        ax.set_axisbelow(True)

    axes[0][0].set_ylim(y_min, y_max)
    axes[0][0].set_ylabel(unit)
    fig.tight_layout()
    return fig


def _waterfall_slide(prs, layouts, config: Config, screens, in_euros: bool):
    title = (
        "Where the money goes, in euros" if in_euros else "Where the money goes, in big blinds"
    )
    slide = pc.add_image_slide(prs, layouts, title, _waterfall_figure(screens, config, in_euros))
    _footnote(
        slide,
        "Shared y axis across stakes - that comparison is the point. "
        + (
            "In euros every bar grows with the stake, which is the entire case for moving up."
            if in_euros
            else "In big blinds the rake bar shrinks as stakes rise, but the win rate shrinks "
            "faster: cheaper rake does not, on this data, pay for the tougher games."
        ),
    )
    return slide


# --------------------------------------------------------------------------- #
# Slide 5 - the chosen configuration and its neighbours
# --------------------------------------------------------------------------- #
def _configurations_slide(prs, layouts, config: Config, allocations, edge, best):
    slide = prs.slides.add_slide(layouts["Title and Content"])
    pc.add_title(slide, "The chosen mix, and its nearest alternatives")

    # Two safer and two bolder neighbours ON THE FRONTIER, so every row shown is
    # a real option rather than an arbitrary nearby allocation.
    index = next((i for i, a in enumerate(edge) if best and a.counts == best.counts), None)
    if index is None:
        window = edge[:5]
        chosen = None
    else:
        low = max(0, index - 2)
        window = edge[low:index + 3]
        chosen = best.counts

    rows_data = []
    for allocation in window:
        is_best = chosen is not None and allocation.counts == chosen
        if is_best:
            note, bg = "CHOSEN - highest EUR/hr inside tolerance", pc.COL_GREEN
        elif allocation.risk_of_ruin < (best.risk_of_ruin if best else 0):
            note, bg = "safer, earns less", None
        else:
            note, bg = "over your tolerance", pc.TABLE_LABEL_BG
        rows_data.append((allocation, note, bg, is_best))

    _allocation_table(slide, config, rows_data, pc.CONTENT_TOP + Inches(0.55))
    _footnote(
        slide,
        f"Tolerance {config.ruin_tolerance:.2%} on a EUR {config.bankroll_eur:,.0f} bankroll "
        f"across {config.tables} tables. Risk of ruin assumes this mix is played at a fixed "
        "size forever, so it is an upper bound - in practice you would move down. "
        "SD is the euro standard deviation per 100 hands: the risk being bought. "
        + drawdown_note(config),
    )
    return slide


def _allocation_table(slide, config: Config, rows_data, top):
    """The shared allocation table: configuration, money, risk, a note.

    Used by the frontier-neighbours slide and the single-stake slide so the two
    can be read against each other without the eye re-learning a layout.
    `rows_data` is a list of (allocation, note, background, bold).
    """
    columns = [
        ("Configuration", 3.30),
        ("EUR/hr", 1.05),
        ("Banked\nEUR/100", 1.20),
        ("SD\nEUR/100", 1.15),
        ("Risk of\nruin", 1.05),
        ("Median worst\ndownswing", 1.35),
        ("1% worst\ndownswing", 1.30),
        ("", 2.20),
    ]
    table_width = Inches(sum(w for _, w in columns))
    left = int(pc.CONTENT_LEFT + (pc.CONTENT_WIDTH - table_width) / 2)
    shape = slide.shapes.add_table(
        len(rows_data) + 1, len(columns), left, top,
        table_width, Inches(0.45 + 0.38 * len(rows_data)),
    )
    table = shape.table
    for i, (_, width) in enumerate(columns):
        table.columns[i].width = Inches(width)
    for i, (label, _) in enumerate(columns):
        cell = table.cell(0, i)
        pc._zero_cell_margins(cell)
        pc.set_cell(cell, label, font_size=10, bold=True,
                    bg_colour=pc.TABLE_HEADER_BG, font_colour=pc.WHITE, wrap=True)

    for row, (allocation, note, bg, bold) in enumerate(rows_data, start=1):
        swing = sim.expected_drawdown(config, allocation, config.timescale_hands)
        values = [
            allocation.label,
            f"{allocation.eur_per_hour:,.0f}",
            f"{allocation.mean_eur_per_100:,.2f}",
            f"{allocation.stdev_eur_per_100:,.0f}",
            f"{allocation.risk_of_ruin:.2%}",
            f"{swing['median']:,.0f}",
            f"{swing['p99']:,.0f}",
            note,
        ]
        for i, value in enumerate(values):
            cell = table.cell(row, i)
            pc._zero_cell_margins(cell)
            pc.set_cell(cell, value, font_size=10, bold=bold, bg_colour=bg)
    return table


def _single_stake_slide(prs, layouts, config: Config, screens, best):
    """Every stake played on its own, in the same format as the mix table.

    The baseline the whole exercise argues against: put all twelve tables on one
    stake and this is what you get. Shown immediately before the frontier so the
    reader has the single-stake numbers in mind when the mixes appear.
    """
    slide = prs.slides.add_slide(layouts["Title and Content"])
    pc.add_title(slide, "If you played one stake and nothing else")

    rows_data = []
    for index, screen in enumerate(screens):
        counts = tuple(config.tables if i == index else 0 for i in range(len(config.stakes)))
        allocation = mix.evaluate(counts, config)
        if not screen.kept:
            note, bg = f"excluded - {screen.excluded_reason}", pc.TABLE_LABEL_BG
        elif allocation.within_tolerance:
            note, bg = "inside tolerance", None
        else:
            note, bg = "over your tolerance", pc.TABLE_LABEL_BG
        rows_data.append((allocation, note, bg, False))

    _allocation_table(slide, config, rows_data, pc.CONTENT_TOP + Inches(0.45))
    best_line = (
        f" The best mix does {best.eur_per_hour:,.0f} EUR/hr at "
        f"{best.risk_of_ruin:.2%} - compare that against every row here."
        if best is not None else ""
    )
    _footnote(
        slide,
        f"All {config.tables} tables on one stake, the configuration conventional bankroll "
        "advice assumes. Note how quickly risk of ruin climbs relative to the earnings: the "
        "rungs are far apart in risk and close together in money, which is exactly the gap a "
        "mix exploits." + best_line + " " + drawdown_note(config),
    )
    return slide


# --------------------------------------------------------------------------- #
# The price of stepping up
# --------------------------------------------------------------------------- #
def _comparison_table(slide, config: Config, baseline, baseline_note, rows_data, top):
    """Shared table: a highlighted baseline mix, then variants with deltas."""
    columns = [
        ("", 3.30),
        ("Configuration", 3.20),
        ("EUR/hr", 1.05),
        ("vs base", 1.05),
        ("Risk of ruin", 1.15),
        ("vs base", 0.95),
        ("Median worst\ndownswing", 1.30),
        ("1% worst\ndownswing", 1.25),
        ("", 1.25),
    ]
    table_width = Inches(sum(w for _, w in columns))
    left = int(pc.CONTENT_LEFT + (pc.CONTENT_WIDTH - table_width) / 2)
    shape = slide.shapes.add_table(
        len(rows_data) + 2, len(columns), left, top,
        table_width, Inches(0.45 + 0.40 * (len(rows_data) + 1)),
    )
    table = shape.table
    for i, (_, width) in enumerate(columns):
        table.columns[i].width = Inches(width)
    for i, (label, _) in enumerate(columns):
        cell = table.cell(0, i)
        pc._zero_cell_margins(cell)
        pc.set_cell(cell, label, font_size=10, bold=True,
                    bg_colour=pc.TABLE_HEADER_BG, font_colour=pc.WHITE, wrap=True)

    def swings(allocation):
        value = sim.expected_drawdown(config, allocation, config.timescale_hands)
        return [f"{value['median']:,.0f}", f"{value['p99']:,.0f}"]

    base_row = [
        baseline_note, baseline.label, f"{baseline.eur_per_hour:,.0f}", "-",
        f"{baseline.risk_of_ruin:.2%}", "-", *swings(baseline), "",
    ]
    for i, value in enumerate(base_row):
        cell = table.cell(1, i)
        pc._zero_cell_margins(cell)
        pc.set_cell(cell, value, font_size=10, bold=True, bg_colour=pc.COL_GREEN, wrap=True)

    for row, (label, allocation, note, inside) in enumerate(rows_data, start=2):
        values = [
            label, allocation.label, f"{allocation.eur_per_hour:,.0f}",
            f"{allocation.eur_per_hour - baseline.eur_per_hour:+,.0f}",
            f"{allocation.risk_of_ruin:.2%}",
            f"{allocation.risk_of_ruin / max(baseline.risk_of_ruin, 1e-12):.1f}x",
            *swings(allocation), note,
        ]
        for i, value in enumerate(values):
            cell = table.cell(row, i)
            pc._zero_cell_margins(cell)
            pc.set_cell(
                cell, value, font_size=10, wrap=True,
                bg_colour=None if inside else pc.TABLE_LABEL_BG,
                font_colour=pc.COL_TEXT_RED if (not inside and i == 8) else None,
            )
    return table


def _step_up_slide(prs, layouts, config: Config, best, options):
    slide = prs.slides.add_slide(layouts["Title and Content"])
    pc.add_title(slide, "The two ways up, and what each costs")

    if not options:
        box = slide.shapes.add_textbox(
            pc.CONTENT_LEFT, pc.CONTENT_TOP + Inches(0.6), pc.CONTENT_WIDTH, Inches(1)
        )
        run = box.text_frame.paragraphs[0].add_run()
        run.text = "The optimal mix already sits at the top of the ladder."
        run.font.size = Pt(12)
        return slide

    rows = [
        (
            option.label,
            option.allocation,
            "inside tolerance" if option.within_tolerance else "OVER tolerance",
            option.within_tolerance,
        )
        for option in options
    ]
    _comparison_table(slide, config, best, "OPTIMAL (baseline)", rows,
                      pc.CONTENT_TOP + Inches(0.55))
    _footnote(
        slide,
        "Two moves that keep the table count fixed and start from where you already are: "
        "reach at the top (one table of the highest stake goes up a rung) or consolidate at "
        "the bottom (one table of the lowest stake goes up one). " + drawdown_note(config),
    )
    return slide


BANKROLL_STEPS = (0.0, 0.10, 0.25, 0.50, 1.00)
"""Growth multiples to re-solve the optimum at. Deliberately proportional rather
than absolute: what matters is how far the roll has moved, not where it started."""


def bankroll_ladder(config: Config):
    """The optimum re-solved at each growth step.

    Yields (label, bankroll, scenario config, allocation). Each row is a fresh,
    independent problem - the same closed-form calculation the deck opens with,
    run at a larger roll. Shared with the simulation-priming pass so the
    downswing figures are computed once, at the RIGHT bankroll for each row.
    """
    rows = []
    for step in BANKROLL_STEPS:
        bankroll = config.bankroll_eur * (1 + step)
        scenario = config.replace(bankroll_eur=bankroll)
        allocation = mix.best_allocation(mix.all_allocations(scenario))
        rows.append((f"+{step:.0%}" if step else "now", bankroll, scenario, allocation))
    return rows


def _bankroll_ladder_slide(prs, layouts, config: Config, best):
    slide = prs.slides.add_slide(layouts["Title and Content"])
    pc.add_title(slide, "What to play as the bankroll grows")

    columns = [
        ("Bankroll", 1.00),
        ("", 1.20),
        ("Optimal mix", 3.30),
        ("EUR/hr", 0.95),
        ("vs now", 0.95),
        ("Risk of\nruin", 1.00),
        ("Median worst\ndownswing", 1.30),
        ("1% worst\ndownswing", 1.25),
        ("", 1.40),
    ]
    rows = bankroll_ladder(config)
    table_width = Inches(sum(w for _, w in columns))
    left = int(pc.CONTENT_LEFT + (pc.CONTENT_WIDTH - table_width) / 2)
    shape = slide.shapes.add_table(
        len(rows) + 1, len(columns), left, pc.CONTENT_TOP + Inches(0.55),
        table_width, Inches(0.45 + 0.40 * len(rows)),
    )
    table = shape.table
    for i, (_, width) in enumerate(columns):
        table.columns[i].width = Inches(width)
    for i, (label, _) in enumerate(columns):
        cell = table.cell(0, i)
        pc._zero_cell_margins(cell)
        pc.set_cell(cell, label, font_size=10, bold=True,
                    bg_colour=pc.TABLE_HEADER_BG, font_colour=pc.WHITE, wrap=True)

    previous_top = None
    for row, (label, bankroll, scenario, allocation) in enumerate(rows, start=1):
        is_now = label == "now"
        if allocation is None:
            values = [label, f"EUR {bankroll:,.0f}", "nothing clears tolerance",
                      "-", "-", "-", "-", "-", ""]
        else:
            top = max(i for i, c in enumerate(allocation.counts) if c)
            note = "where you should be now" if is_now else (
                f"unlocks {config.stakes[top].name}"
                if previous_top is not None and top > previous_top else ""
            )
            previous_top = top
            swing = sim.expected_drawdown(scenario, allocation, config.timescale_hands)
            values = [
                label,
                f"EUR {bankroll:,.0f}",
                allocation.label,
                f"{allocation.eur_per_hour:,.0f}",
                f"{allocation.eur_per_hour - best.eur_per_hour:+,.0f}" if best else "-",
                f"{allocation.risk_of_ruin:.2%}",
                f"{swing['median']:,.0f}",
                f"{swing['p99']:,.0f}",
                note,
            ]
        for i, value in enumerate(values):
            cell = table.cell(row, i)
            pc._zero_cell_margins(cell)
            pc.set_cell(cell, value, font_size=10, bold=is_now,
                        bg_colour=pc.COL_GREEN if is_now else None, wrap=True)

    _footnote(
        slide,
        "Each row is the optimum re-solved from scratch at that bankroll, at the same "
        f"{config.ruin_tolerance:.2%} tolerance - a fresh problem, not a path. It does not "
        "model getting there: no move-down rule and no order of play, just the right answer "
        "if you were standing at that roll today. Risk of ruin and both downswing figures are "
        "measured from that row's bankroll as the starting point. " + drawdown_note(config),
    )
    return slide


def _current_slide(prs, layouts, config: Config, best, current):
    slide = prs.slides.add_slide(layouts["Title and Content"])
    pc.add_title(slide, "What you are actually playing")

    dominated = (
        current.eur_per_hour < best.eur_per_hour and current.risk_of_ruin > best.risk_of_ruin
    )
    note = "worse on BOTH axes" if dominated else "the mix in play"
    rows = [(
        "CURRENT (July)", current, note,
        current.within_tolerance and not dominated,
    )]
    _comparison_table(slide, config, best, "OPTIMAL (baseline)", rows,
                      pc.CONTENT_TOP + Inches(0.55))

    _footnote(
        slide,
        "Reconstructed from hands actually played per stake in July, apportioned to whole "
        f"tables by largest remainder. "
        + (
            "This configuration is DOMINATED: the optimal mix earns more AND carries less "
            "risk of ruin, so moving to it is not a trade-off - there is no side on which "
            "the current split is better."
            if dominated
            else "Compare against the optimum above."
        ),
    )
    return slide


# --------------------------------------------------------------------------- #
# Slide 7 - the simulation
# --------------------------------------------------------------------------- #
def _simulation_slide(prs, layouts, config: Config, result, title):
    import numpy as np

    slide = pc.add_image_slide(
        prs, layouts, title, charts.simulation_figure(result, config)
    )
    median_dd = float(np.percentile(result.max_drawdown, 50))
    p90_dd = float(np.percentile(result.max_drawdown, 90))
    median_end = float(np.percentile(result.final_bankroll, 50))
    over_roll = (
        " Note the typical worst drawdown EXCEEDS the starting bankroll while only "
        f"{result.ruin_probability:.2%} go broke: by the time the deep falls arrive, most "
        "lifetimes are playing with winnings, not with the money they started on."
        if median_dd > config.bankroll_eur
        else ""
    )
    _footnote(
        slide,
        f"{result.allocation.label}. {result.hands:,} hands ({result.hours:,.0f} hours at "
        f"{config.tables} tables) per lifetime, played at a fixed mix with no move-down rule - "
        f"an upper bound on risk, not a forecast. Typical worst drawdown EUR {median_dd:,.0f}, "
        f"one lifetime in ten worse than EUR {p90_dd:,.0f}, median finish EUR "
        f"{median_end:,.0f}." + over_roll,
    )
    return slide


# --------------------------------------------------------------------------- #
# Slide 8 - methodology
# --------------------------------------------------------------------------- #
def _methodology_slide(prs, layouts, config: Config):
    slide = prs.slides.add_slide(layouts["Title and Content"])
    pc.add_title(slide, "Appendix: method, and what it assumes")

    body = slide.shapes.add_textbox(
        pc.CONTENT_LEFT, pc.CONTENT_TOP, pc.CONTENT_WIDTH, pc.CONTENT_HEIGHT
    )
    frame = body.text_frame
    frame.word_wrap = True

    sections = [
        ("The question", [
            "Which distribution of tables across stakes earns the most, without exceeding a "
            "chosen risk of ruin. Volume is divisible across tables, so the decision variable "
            "is the share of tables at each stake, not a single stake.",
        ]),
        ("The maths", [
            "Per 100 hands dealt across all tables, a mix has mean  SUM (n/T) x winrate x bb, "
            "and variance  SUM (n/T) x sd^2 x bb^2, both in euros. Tables deal independent "
            "hands, so these are exact, not simulated.",
            "Risk of ruin follows the standard diffusion result  R = exp(-2 x mean x bankroll "
            "/ variance).  P(lose half) is the same formula with the barrier moved up.",
            "Every allocation is enumerated and scored - a few hundred to a few thousand - so "
            "the optimum is found by brute force. No sampling and no search heuristic.",
        ]),
        ("Rakeback", [
            f"Rebated at {config.rakeback_pct:.0%} of rake paid. It is a rebate on volume, not "
            "a gamble: it raises the mean and adds NO variance, which is why it both increases "
            "earnings and reduces risk of ruin.",
            "Win rates are already net of rake, so adding rakeback does not double-count.",
        ]),
        ("What is assumed, not measured", [
            "Standard deviation is a flat 92 bb/100 at every stake - an assumption. If real "
            "variance falls as stakes rise, the higher stakes are being penalised here.",
            "Tables are treated as independent. Multi-tabling correlates outcomes within a "
            "session, which would raise effective variance.",
            "No win-rate penalty is charged for table count.",
            "Ruin assumes the mix is played at a fixed size forever, with no move-down rule. "
            "That makes it a conservative constraint and a poor forecast.",
        ]),
        ("Known weaknesses in the inputs", [
            "Only the lowest stakes are well measured. A win rate's 95% interval is roughly "
            "+/-3.5 bb/100 at 271k hands and +/-16.5 at 12k, so the higher rungs of the ladder "
            "rest on thin samples.",
            "Stakes with a few hundred hands are held out entirely rather than allowed to "
            "dominate the answer on noise.",
        ]),
        ("Two kinds of downswing, and why only one has a closed form", [
            "LOSS BELOW STARTING BANKROLL is what ruin measures - start on 10k, run to 15k, "
            "fall to 5k, and that is a 5k loss below start. Over unlimited time it is bounded "
            "and exactly exponential, so its quantiles are exact. The 99th percentile of it "
            "IS your bankroll, by construction, at a 1% tolerance.",
            "PEAK-TO-TROUGH DRAWDOWN is what a downswing feels like - the same episode above "
            "is a 10k fall. It has NO all-time value: given unlimited time it grows without "
            "bound, because a winning bankroll keeps making new highs to fall from. Every "
            "peak-to-trough figure here is therefore 'within this many hands' and nothing "
            "more. That is the reason the simulation exists.",
        ]),
        ("The simulation", [
            f"{config.timescale_hands:,} hands per lifetime, {config.sim_paths:,} independent "
            "lifetimes, ruin absorbing (a busted path stops rather than trading back).",
            "Hands are drawn in 100-hand blocks, the unit the win rate and variance arrive "
            "in - exact for a diffusion, though a dip and recovery inside one block goes "
            "unseen.",
            "Checked against the closed form: over a long horizon its loss-below-start "
            "distribution must reproduce the analytic exponential. A simulation that "
            "disagrees where the maths is known has a bug.",
        ]),
        ("Not modelled", [
            "The allocation is a static snapshot at one bankroll, in the analytics AND in the "
            "simulation. The dynamic version - move up through one threshold, down through "
            "another, with hysteresis - is not built. Since a real player moves down long "
            "before busting, every risk number here is an upper bound.",
        ]),
    ]

    first = True
    for heading, points in sections:
        para = frame.paragraphs[0] if first else frame.add_paragraph()
        first = False
        run = para.add_run()
        run.text = heading
        run.font.size = Pt(12)
        run.font.bold = True
        para.space_before = Pt(0 if heading == "The question" else 7)
        for point in points:
            bullet = frame.add_paragraph()
            bullet.level = 1
            run = bullet.add_run()
            run.text = point
            run.font.size = Pt(10)
            run.font.color.rgb = pc.BLACK
    return slide


# --------------------------------------------------------------------------- #
def _footnote(slide, text):
    box = slide.shapes.add_textbox(
        pc.CONTENT_LEFT,
        pc.CONTENT_TOP + pc.CONTENT_HEIGHT - Inches(0.85),
        pc.CONTENT_WIDTH,
        Inches(0.8),
    )
    frame = box.text_frame
    frame.word_wrap = True
    run = frame.paragraphs[0].add_run()
    run.text = text
    run.font.size = Pt(9)
    run.font.italic = True
    run.font.color.rgb = pc.GRID_GREY
    return box


def _mixes_needing_simulation(config: Config, screens, edge, best, current):
    """Every allocation that will appear in a table, de-duplicated, in order."""
    wanted = []

    def want(allocation):
        if allocation is not None and allocation.counts not in {a.counts for a in wanted}:
            wanted.append(allocation)

    for index in range(len(config.stakes)):  # the single-stake slide
        want(mix.evaluate(
            tuple(config.tables if i == index else 0 for i in range(len(config.stakes))),
            config,
        ))
    if best is not None:
        position = next((i for i, a in enumerate(edge) if a.counts == best.counts), None)
        window = edge[max(0, position - 2):position + 3] if position is not None else edge[:5]
        for allocation in window:
            want(allocation)
        for option in mix.step_up_options(config, best):
            want(option.allocation)
    want(current)
    return wanted


def _prime_simulations(config: Config, screens, edge, best, current) -> dict:
    """Run every simulation the deck needs, with a progress bar.

    Returns the full-detail results for the headline charts, keyed by
    allocation, so they are not simulated a second time when those slides are
    built. The per-table figures go into sim's own cache.
    """
    wanted = _mixes_needing_simulation(config, screens, edge, best, current)
    headline = [a for a in (best, current) if a is not None]
    # The ladder rows each carry their OWN bankroll, so they cannot share the
    # cache entries above even where the allocation happens to match.
    ladder = [
        (scenario, allocation, label)
        for label, _, scenario, allocation in bankroll_ladder(config)
        if allocation is not None and label != "now"
    ]

    total = len(wanted) + len(ladder) + len(headline)
    print(f"\nSTEP 3 - SIMULATIONS   ({total} mixes x {config.timescale_hands:,} hands)")
    bar = progress.Progress(total, "simulations")
    bar.draw("starting")

    for allocation in wanted:
        sim.expected_drawdown(config, allocation, config.timescale_hands)
        bar.advance(allocation.label)

    for scenario, allocation, label in ladder:
        sim.expected_drawdown(scenario, allocation, config.timescale_hands)
        bar.advance(f"{allocation.label} (bankroll {label})")

    results = {}
    for allocation in headline:
        # The headline charts run at the full path count for a smooth histogram;
        # the table figures use fewer, which is plenty for a percentile.
        results[allocation.counts] = sim.simulate(
            config, allocation, hands=config.timescale_hands, paths=config.sim_paths
        )
        bar.advance(f"{allocation.label} (full detail)")

    bar.close(f"{total} mixes simulated over {config.timescale_hands:,} hands each.")
    return results


def build(config: Config, directory: Path) -> Path:
    """Build the deck and return the path written."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "shot_take_optimisation.pptx"

    screens = mix.screen_stakes(config)
    allocations = mix.all_allocations(config)
    edge = mix.frontier(allocations)
    best = mix.best_allocation(allocations)

    current = mix.current_allocation(config)

    # Simulate everything the deck will need BEFORE building any slides, so the
    # work is visible as one progress bar rather than as a series of unexplained
    # pauses while tables render. Results land in sim's cache; the table code
    # then finds them already there.
    simulations = _prime_simulations(config, screens, edge, best, current)

    prs, layouts = pc.load_template_presentation()

    def run_sim(allocation):
        return simulations[allocation.counts]

    # ---- 1. Where the tables should be ------------------------------------- #
    pc.add_chapter_slide(
        prs, layouts, "1. Optimal stake distribution",
        "Which stakes are worth playing, and in what proportion",
    )
    _stake_table_slide(prs, layouts, config, screens)
    _waterfall_slide(prs, layouts, config, screens, in_euros=False)
    _waterfall_slide(prs, layouts, config, screens, in_euros=True)
    _single_stake_slide(prs, layouts, config, screens, best)
    pc.add_image_slide(
        prs, layouts, "Every way to split the tables",
        charts.allocation_frontier_figure(config),
    )
    _configurations_slide(prs, layouts, config, allocations, edge, best)
    if best is not None:
        _simulation_slide(
            prs, layouts, config, run_sim(best),
            "The optimal mix, simulated",
        )

    # ---- 2. Moving up ------------------------------------------------------ #
    if best is not None:
        pc.add_chapter_slide(
            prs, layouts, "2. Shot-taking",
            "What it costs to move a table up a rung",
        )
        _step_up_slide(prs, layouts, config, best, mix.step_up_options(config, best))

    # ---- 3. The same question at a bigger roll ----------------------------- #
    if best is not None:
        pc.add_chapter_slide(
            prs, layouts, "3. As the bankroll grows",
            "Where the mix should go as the roll gets bigger",
        )
        _bankroll_ladder_slide(prs, layouts, config, best)

    # ---- 4. What is actually happening ------------------------------------- #
    if current is not None and best is not None:
        pc.add_chapter_slide(
            prs, layouts, "4. Current configuration",
            "How the table time was really split, and what that costs",
        )
        _current_slide(prs, layouts, config, best, current)
        _simulation_slide(
            prs, layouts, config, run_sim(current),
            "The mix you actually played, simulated",
        )

    _methodology_slide(prs, layouts, config)

    prs.save(path)
    return path
