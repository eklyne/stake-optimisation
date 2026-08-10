"""The frontier chart.

One chart, because there is one question. Colours are the reference data-viz
values used verbatim rather than re-derived; the chart renders on the light
surface only, since a PNG has no viewer theme to respond to. Colour carries
in/out of tolerance - a status, not an identity - and is always paired with a
shape and a direct label, so it never has to be read by hue alone.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no display on this box; also keeps runs headless
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter, MaxNLocator  # noqa: E402

from . import mix  # noqa: E402
from .config import Config  # noqa: E402

__all__ = [
    "write_all",
    "allocation_frontier",
    "allocation_frontier_figure",
    "simulation_figure",
    "random_paths_figure",
    "simulation_scales",
    "winrate_ci_figure",
]

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#7a7972"
GRID = "#e8e7e4"

SERIES_BLUE = "#2a78d6"
STATUS_GOOD = "#0ca30c"
STATUS_CRITICAL = "#d03b3b"

RUIN_FLOOR = 1e-6
"""Ruin probabilities below this are plotted at the floor - the difference
between 1-in-a-million and 1-in-a-trillion is not a decision-relevant one."""


def _style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "savefig.facecolor": SURFACE,
            "axes.edgecolor": GRID,
            "axes.labelcolor": INK_SECONDARY,
            "axes.titlecolor": INK,
            "axes.titlesize": 13,
            "axes.titleweight": "bold",
            "axes.titlelocation": "left",
            "axes.titlepad": 30,  # leaves room for the subtitle line beneath it
            "axes.labelsize": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "xtick.color": INK_SECONDARY,
            "ytick.color": INK_SECONDARY,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "grid.color": GRID,
            "grid.linewidth": 0.8,
            "legend.frameon": False,
            "legend.fontsize": 9,
            "legend.labelcolor": INK_SECONDARY,
            "font.size": 10,
            "figure.dpi": 150,
        }
    )


def _subtitle(ax, text: str) -> None:
    """One line of plain-English context, sitting between title and plot."""
    ax.annotate(
        text,
        xy=(0, 1.0),
        xycoords="axes fraction",
        xytext=(0, 9),
        textcoords="offset points",
        fontsize=9.5,
        color=INK_SECONDARY,
        va="bottom",
    )


def _finish(fig, path: Path) -> Path:
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def allocation_frontier_figure(config: Config):
    """Every way to split the tables, plotted as EUR/hour against risk.

    The cloud is every allocation; the line through its upper-left edge is the
    efficient frontier - the mixes nothing else beats on both axes. The best
    point inside tolerance is the answer, and the frontier's shape shows what
    each further step of risk actually buys.

    Returns the figure so the deck can embed it as vector-quality output rather
    than re-reading a rendered PNG.
    """
    _style()
    fig, ax = plt.subplots(figsize=(9.5, 6))

    allocations = mix.all_allocations(config)
    edge = mix.frontier(allocations)
    best = mix.best_allocation(allocations)

    ax.scatter(
        [max(a.risk_of_ruin, RUIN_FLOOR) for a in allocations],
        [a.eur_per_hour for a in allocations],
        s=14, color=INK_MUTED, alpha=0.28, linewidths=0, label="Every possible mix",
    )
    ax.plot(
        [max(a.risk_of_ruin, RUIN_FLOOR) for a in edge],
        [a.eur_per_hour for a in edge],
        color=SERIES_BLUE, linewidth=2.0, marker="o", markersize=5,
        markeredgecolor=SURFACE, markeredgewidth=1, label="Efficient frontier",
    )

    ax.axvline(config.ruin_tolerance, color=INK_MUTED, linewidth=1.4, linestyle="--")
    ax.annotate(
        f"tolerance {config.ruin_tolerance:.1%}",
        xy=(config.ruin_tolerance, 0.02),
        xycoords=("data", "axes fraction"),
        xytext=(-6, 0), textcoords="offset points", ha="right",
        color=INK_MUTED, fontsize=9,
    )

    if best is not None:
        ax.plot(
            [max(best.risk_of_ruin, RUIN_FLOOR)], [best.eur_per_hour],
            marker="o", markersize=13, color=STATUS_GOOD,
            markeredgecolor=SURFACE, markeredgewidth=2, linestyle="none",
            label="Best inside tolerance",
        )
        ax.annotate(
            f"{best.label}\n{best.eur_per_hour:,.0f} EUR/hr",
            xy=(max(best.risk_of_ruin, RUIN_FLOOR), best.eur_per_hour),
            xytext=(-14, 6), textcoords="offset points", ha="right",
            color=INK, fontsize=9.5, fontweight="bold",
        )

    # The mix actually being played, so the gap to the frontier is visible rather
    # than described. Its vertical distance to the blue line is EV left on the
    # table; its horizontal distance is risk taken for nothing.
    current = mix.current_allocation(config)
    if current is not None:
        ax.plot(
            [max(current.risk_of_ruin, RUIN_FLOOR)], [current.eur_per_hour],
            marker="D", markersize=11, color=STATUS_CRITICAL,
            markeredgecolor=SURFACE, markeredgewidth=2, linestyle="none",
            label="What you are playing now",
        )
        ax.annotate(
            f"current: {current.eur_per_hour:,.0f} EUR/hr",
            xy=(max(current.risk_of_ruin, RUIN_FLOOR), current.eur_per_hour),
            xytext=(10, -14), textcoords="offset points",
            color=STATUS_CRITICAL, fontsize=9.5, fontweight="bold",
        )

    ax.set_xscale("log")
    ax.set_xlim(RUIN_FLOOR / 3.0, 3.0)
    ax.margins(y=0.15)
    # The stack of points on the left edge is the floor, not a coincidence: those
    # mixes all carry a risk too small to tell apart or to care about.
    ax.set_xlabel(
        f"Risk of ruin (log scale; under {RUIN_FLOOR:g} is drawn at the floor)"
    )
    ax.set_ylabel("EUR / hour")
    ax.grid(alpha=0.9)
    ax.set_axisbelow(True)
    ax.set_title(f"Every way to split {config.tables} tables across your stakes")
    _subtitle(
        ax,
        "Take the highest point left of the dashed line. The frontier is the menu; "
        "everything below it is dominated.",
    )
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncols=3)
    fig.tight_layout()
    return fig


def allocation_frontier(config: Config, path: Path) -> Path:
    """Render the frontier chart to `path`."""
    fig = allocation_frontier_figure(config)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


RANDOM_PATHS = 20
"""Lifetimes drawn on the spaghetti chart. Enough to show the spread, few
enough that a single line can still be followed across the page."""

_RANDOM_PATH_SEED = 90210
"""Fixed, so the same twenty lifetimes appear every rebuild. A chart that
reshuffles on every run invites the reader to rerun until they like it."""


COL_RAKEBACK = "#1baf7a"

EUR_HOUR_CEILING = 300.0
"""Top of the EUR/hour panel. The thin stakes' intervals run into four figures;
letting them set the scale flattens every bar into the bottom inch to show a
whisker nobody needs to read precisely. Clipped ends are marked with an arrow."""


def winrate_ci_figure(screens, config: Config):
    """Win rate and rakeback per stake, with the interval around the MEASUREMENT.

    Two panels, same stakes, two units: bb/100 is how a poker player states an
    edge, EUR/hour is what it is worth. They rank the stakes in OPPOSITE orders,
    which is the whole tension the deck resolves, so both are shown.

    The bar is what the MODEL uses. The diamond is what the SAMPLE says, and the
    interval belongs to the diamond, never to the bar - at the stakes where the
    modelled rate is an assumption those are different numbers, and drawing an
    interval around an assumption would present a guess as a measurement. Where
    a stake has no assumption the two coincide and only the bar is drawn.

    Rakeback is stacked on top rather than plotted beside: it is part of what you
    bank, and unlike the win rate it carries NO uncertainty - it is a rebate on
    volume, known in advance. So the interval spans the win-rate portion only.
    """
    import numpy as np

    from . import estimation, rates

    _style()
    fig, (left, right) = plt.subplots(1, 2, figsize=(11.5, 4.3))

    names = [s.stake.name for s in screens]
    x = np.arange(len(screens))
    hours_per_100 = config.tables * config.hands_per_hour_per_table / 100.0

    def bb_ceiling():
        """Scale the bb panel off the stakes whose rate IS the measurement.

        The assumed stakes have intervals of +/-50 and worse. Letting those set
        the height flattens every honest bar into the bottom inch to show a
        whisker whose only message is 'we know nothing here' - which the arrow
        already says.
        """
        highs = []
        for screen in screens:
            stake = screen.stake
            back = rates.rakeback_bb100(stake.rake_bb100, config.rakeback_pct)
            highs.append(stake.winrate_bb100 + back)
            if stake.hands and stake.measured_winrate_bb100 is None:
                highs.append(
                    stake.winrate_bb100 + back
                    + estimation.Z_95 * estimation.winrate_stderr(
                        stake.stdev_bb100, stake.hands)
                )
        return max(highs) * 1.12

    for ax, in_euros in ((left, False), (right, True)):
        ceiling = EUR_HOUR_CEILING if in_euros else bb_ceiling()
        tops = []
        for index, screen in enumerate(screens):
            stake = screen.stake
            rakeback = rates.rakeback_bb100(stake.rake_bb100, config.rakeback_pct)
            # One conversion factor per panel: bb/100 -> EUR/hour across the
            # whole table count, or 1.0 to stay in big blinds.
            scale = stake.bb_eur * hours_per_100 if in_euros else 1.0
            back = rakeback * scale
            modelled = stake.winrate_bb100 * scale + back

            faded = 0.35 if not screen.kept else 1.0
            win = modelled - back
            ax.bar(index, win, width=0.50, color=SERIES_BLUE,
                   alpha=faded, linewidth=0)
            ax.bar(index, back, bottom=win, width=0.50,
                   color=COL_RAKEBACK, alpha=faded, linewidth=0)
            tops.append(modelled)

            # Each segment carries its OWN value, in the middle of itself, and
            # the total sits above the bar. Putting the total inside the stack
            # made it read as the size of whichever segment it landed in.
            def label(value, low, high):
                if high - low < 0.075 * ceiling:  # no room without overlapping
                    return
                ax.annotate(f"{value:,.0f}" if in_euros else f"{value:.2f}",
                            xy=(index, (low + high) / 2), ha="center", va="center",
                            fontsize=8.5, color=SURFACE, fontweight="bold", zorder=7)

            label(modelled - back, 0.0, win)
            label(back, win, modelled)
            ax.annotate(f"{modelled:,.0f}" if in_euros else f"{modelled:.2f}",
                        xy=(index, modelled), xytext=(0, 4),
                        textcoords="offset points", ha="center", va="bottom",
                        fontsize=9.5, color=INK, fontweight="bold", zorder=7)

            assumed = stake.measured_winrate_bb100 is not None
            if stake.hands:
                measured = (
                    stake.measured_winrate_bb100 if assumed else stake.winrate_bb100
                ) * scale + back
                half = estimation.Z_95 * scale * estimation.winrate_stderr(
                    stake.stdev_bb100, stake.hands
                )
                low, high = measured - half, measured + half
                lo_clip, hi_clip = low < 0, high > ceiling
                lo_y, hi_y = max(low, 0.0), min(high, ceiling)
                # Offset to the right of the bar rather than through it, so the
                # total above the bar has clear air and the interval is legible
                # as its own mark.
                at = index + 0.32
                ax.plot([at, at], [lo_y, hi_y], color=INK, linewidth=1.3,
                        solid_capstyle="butt", zorder=4)
                for y, clipped, marker in ((lo_y, lo_clip, "v"), (hi_y, hi_clip, "^")):
                    if clipped:
                        ax.plot([at], [y], marker=marker, markersize=7,
                                color=STATUS_CRITICAL, zorder=5)
                    else:
                        ax.plot([at - 0.09, at + 0.09], [y, y],
                                color=INK, linewidth=1.3, zorder=4)
                # The measurement itself, so the gap to the modelled bar is
                # visible rather than described in a footnote. Off-scale
                # measurements are left to the arrow rather than pinned to the
                # edge, where a diamond would read as a real value.
                if assumed and 0.0 <= measured <= ceiling:
                    ax.plot([at], [measured], marker="D", markersize=6,
                            color=INK, markeredgecolor=SURFACE, markeredgewidth=1,
                            zorder=6)
                tops.append(hi_y)
            else:
                ax.annotate("no sample", xy=(index, modelled),
                            xytext=(0, 5), textcoords="offset points", ha="center",
                            fontsize=7.5, color=INK_MUTED, fontweight="bold")


        ax.set_xticks(x, names, fontsize=9)
        ax.set_ylim(0, ceiling)
        ax.grid(axis="y", alpha=0.9)
        ax.set_axisbelow(True)
        if in_euros:
            ax.set_ylabel(f"EUR / hour across {config.tables} tables")
            ax.set_title("What that edge is worth")
            _subtitle(right, f"Same edges, priced in money. Axis capped at "
                             f"EUR {EUR_HOUR_CEILING:,.0f}/hr.")
        else:
            ax.set_ylabel("bb / 100 hands")
            ax.set_title("The edge, and how well it is known")
            _subtitle(left, "Bar: the rate the model uses. Diamond: the sample. "
                            "Arrow: interval runs off the axis.")

    handles = [
        plt.Rectangle((0, 0), 1, 1, color=SERIES_BLUE),
        plt.Rectangle((0, 0), 1, 1, color=COL_RAKEBACK),
        plt.Line2D([0], [0], color=INK, linewidth=1.3, marker="D", markersize=6),
    ]
    fig.legend(
        handles,
        ["Win rate used by the model", f"Rakeback at {config.rakeback_pct:.0%}",
         "Measured all-in rate, with its 95% interval"],
        loc="lower center", ncols=3, frameon=False, fontsize=9,
        bbox_to_anchor=(0.5, 0.005),
    )
    fig.tight_layout(rect=(0, 0.09, 1, 1))
    return fig


def _random_rows(result):
    """The lifetimes the spaghetti chart will draw.

    Split out from the chart so the axis-limit pass can ask the same question
    and get the same answer - a shared axis computed off different paths than
    the ones drawn would clip them."""
    import numpy as np

    rng = np.random.default_rng(_RANDOM_PATH_SEED)
    total = result.checkpoint_bankroll.shape[0]
    return rng.choice(total, size=min(RANDOM_PATHS, total), replace=False)


def simulation_scales(results, config: Config, allocations=()):
    """One set of axis limits for EVERY simulation chart in the deck.

    Returns (bankroll_ylim, drawdown_xmax). Without this each chart autoscales
    to its own data, and two mixes drawn at different scales look far more alike
    than they are - the whole point of putting them on consecutive slides is
    that the reader can compare heights directly. Computed across every result
    that will be plotted, so the widest one sets the frame and nothing clips.

    `allocations` are the mixes whose EV lines get drawn; their endpoints have
    to fit too, and the EV of a mix NOT being simulated on a given slide can sit
    above everything on it.
    """
    import numpy as np

    top = config.bankroll_eur
    hands = 0
    for result in results:
        hands = max(hands, result.hands)
        # The 95th percentile band is what the fan chart draws; the sampled rows
        # are what the spaghetti chart draws. Both have to fit.
        top = max(top, float(np.percentile(result.checkpoint_bankroll, 95, axis=0).max()))
        top = max(top, float(result.checkpoint_bankroll[_random_rows(result)].max()))
    for allocation in allocations:
        top = max(top, config.bankroll_eur + allocation.mean_eur_per_100 * hands / 100.0)

    # Headroom for the direct labels above the lines, and a strip below zero for
    # the "broke" annotation that hangs under the axis.
    return (-0.07 * top, 1.08 * top), max(
        (float(np.percentile(r.max_drawdown, 99.5)) for r in results), default=None
    )


def simulation_figure(result, config: Config, ylim=None, drawdown_xmax=None):
    """Two panels: where the bankroll goes, and how deep it digs on the way.

    Left is a fan of percentile bands rather than a spaghetti of paths - with
    twenty thousand lifetimes, individual lines are noise. A handful are drawn
    over the top anyway, because a band alone hides how jagged a single real
    year looks.

    Right is the distribution of the worst peak-to-trough fall per lifetime,
    which is the number with no closed form and therefore the reason this
    simulation exists at all.
    """
    import numpy as np

    _style()
    fig, (left, right) = plt.subplots(1, 2, figsize=(11.5, 5.2),
                                      gridspec_kw={"width_ratios": [1.35, 1]})

    hands = result.checkpoint_hands
    bands = [(5, 95, 0.14), (25, 75, 0.24)]
    for low, high, alpha in bands:
        left.fill_between(
            hands,
            np.percentile(result.checkpoint_bankroll, low, axis=0),
            np.percentile(result.checkpoint_bankroll, high, axis=0),
            color=SERIES_BLUE, alpha=alpha, linewidth=0,
        )
    median = np.percentile(result.checkpoint_bankroll, 50, axis=0)
    left.plot(hands, median, color=SERIES_BLUE, linewidth=2.2, label="Median")

    # Sample paths chosen by where they FINISH - the lifetimes that ended at the
    # 5th, 20th, 40th, 60th, 80th and 95th percentile. Drawing a random handful
    # instead would over-represent the middle and never show you a bad year,
    # which is the one you want to look at.
    finals = result.final_bankroll
    order = np.argsort(finals)
    picks = [order[min(int(p / 100 * len(order)), len(order) - 1)]
             for p in (5, 20, 40, 60, 80, 95)]
    for row in picks:
        left.plot(hands, result.checkpoint_bankroll[row], color=INK_MUTED,
                  linewidth=0.8, alpha=0.6)

    # Start and zero are only EUR 5k apart on a EUR 150k axis, so the two labels
    # collide at any shared alignment - they go to opposite ends instead.
    left.axhline(config.bankroll_eur, color=INK_MUTED, linewidth=1.2, linestyle="--")
    left.annotate(f"start EUR {config.bankroll_eur:,.0f}",
                  xy=(1.0, config.bankroll_eur), xycoords=("axes fraction", "data"),
                  xytext=(-4, 6), textcoords="offset points", ha="right",
                  fontsize=9, color=INK_MUTED)
    left.axhline(0, color=STATUS_CRITICAL, linewidth=1.2)
    left.annotate(f"broke - {result.ruin_probability:.2%} of lifetimes", xy=(0, 0),
                  xytext=(4, -14), textcoords="offset points", fontsize=9,
                  color=STATUS_CRITICAL)
    left.set_xlabel("Hands played")
    left.set_ylabel("Bankroll (EUR)")
    left.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v / 1000:.0f}k"))
    left.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    left.grid(axis="y", alpha=0.9)
    left.set_axisbelow(True)
    if ylim is not None:
        left.set_ylim(*ylim)
    left.set_title("Where the bankroll ends up")
    # Kept short: two subtitles sit side by side and a long one runs into its
    # neighbour's panel.
    _subtitle(left, "Bands: 5-95 and 25-75 percentiles. Grey: six lifetimes, by finish.")

    # Clip the tail: a handful of extreme lifetimes otherwise stretch the axis to
    # four times the interesting range and squash the whole distribution left.
    x_max = (
        drawdown_xmax if drawdown_xmax is not None
        else float(np.percentile(result.max_drawdown, 99.5))
    )
    right.hist(result.max_drawdown, bins=60, range=(0, x_max),
               color=SERIES_BLUE, alpha=0.85, linewidth=0)
    for pct, style, height in ((50, "-", 0.97), (90, ":", 0.86)):
        value = float(np.percentile(result.max_drawdown, pct))
        right.axvline(value, color=INK, linewidth=1.4, linestyle=style)
        right.annotate(f"{pct}th: EUR {value:,.0f}", xy=(value, height),
                       xycoords=("data", "axes fraction"), xytext=(6, 0),
                       textcoords="offset points", fontsize=9, color=INK,
                       fontweight="bold", va="top")
    right.axvline(config.bankroll_eur, color=STATUS_CRITICAL, linewidth=1.4, linestyle="--")
    right.annotate("your whole roll", xy=(config.bankroll_eur, 0.50),
                   xycoords=("data", "axes fraction"), xytext=(-6, 0),
                   textcoords="offset points", ha="right", fontsize=9,
                   color=STATUS_CRITICAL)
    right.set_xlim(0, x_max)
    right.xaxis.set_major_locator(MaxNLocator(nbins=6))  # else the labels collide
    right.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    right.set_xlabel("Worst peak-to-trough fall (EUR)")
    right.set_ylabel("Lifetimes")
    right.grid(axis="y", alpha=0.9)
    right.set_axisbelow(True)
    right.set_title("How deep it digs")
    _subtitle(right, "One value per lifetime: its single worst drawdown.")

    fig.tight_layout()
    return fig


def random_paths_figure(result, config: Config, ev_lines=(), ylim=None):
    """Twenty lifetimes, drawn individually, with the EV lines over the top.

    The companion to the fan chart, answering the complaint that a percentile
    band is not a thing anyone experiences. These are twenty lifetimes picked at
    random - NOT by where they finish, which is how the fan chart chooses its
    handful - so the spread is the honest one the simulation produced.

    `ev_lines` is a sequence of (label, allocation, colour): each is drawn as a
    straight dotted line at bankroll + mean x hands, the path the mix would take
    with the variance switched off. Straight because expectation is linear in
    hands - the curvature people expect is a property of compounding, and
    nothing here compounds: the mix is static and the stakes never move.
    """
    import numpy as np

    _style()
    fig, ax = plt.subplots(figsize=(11.5, 5.2))

    hands = result.checkpoint_hands
    rng = np.random.default_rng(_RANDOM_PATH_SEED)
    count = min(RANDOM_PATHS, result.checkpoint_bankroll.shape[0])
    rows = rng.choice(result.checkpoint_bankroll.shape[0], size=count, replace=False)
    for row in rows:
        ax.plot(hands, result.checkpoint_bankroll[row],
                color=SERIES_BLUE, linewidth=0.9, alpha=0.55)

    ax.axhline(config.bankroll_eur, color=INK_MUTED, linewidth=1.2, linestyle="--")
    ax.annotate(f"start EUR {config.bankroll_eur:,.0f}",
                xy=(1.0, config.bankroll_eur), xycoords=("axes fraction", "data"),
                xytext=(-4, 6), textcoords="offset points", ha="right",
                fontsize=9, color=INK_MUTED)
    ax.axhline(0, color=STATUS_CRITICAL, linewidth=1.2)
    ax.annotate(f"broke - {result.ruin_probability:.2%} of lifetimes", xy=(0, 0),
                xytext=(4, -14), textcoords="offset points", fontsize=9,
                color=STATUS_CRITICAL)

    # Drawn last so they sit on top of the spaghetti, and labelled directly at
    # the right-hand end rather than in a legend the eye has to travel to.
    for label, allocation, colour in ev_lines:
        line = config.bankroll_eur + allocation.mean_eur_per_100 * (hands / 100.0)
        ax.plot(hands, line, color=colour, linewidth=2.0, linestyle=":")
        ax.annotate(f"{label} EV  EUR {line[-1]:,.0f}",
                    xy=(hands[-1], line[-1]), xytext=(-4, 8),
                    textcoords="offset points", ha="right", fontsize=9,
                    fontweight="bold", color=colour)

    ax.set_xlabel("Hands played")
    ax.set_ylabel("Bankroll (EUR)")
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v / 1000:.0f}k"))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.grid(axis="y", alpha=0.9)
    ax.set_axisbelow(True)
    if ylim is not None:
        ax.set_ylim(*ylim)
    ax.set_title("Where the bankroll ends up - twenty single lifetimes")
    _subtitle(
        ax,
        f"{count} lifetimes drawn at random from the {result.paths:,} simulated. "
        "Dotted: the EV of each mix, variance switched off.",
    )

    fig.tight_layout()
    return fig


def write_all(config: Config, directory: Path) -> list[Path]:
    """Render the frontier chart into `directory`.

    One chart, deliberately. Earlier versions also drew per-stake ruin curves, a
    Kelly-fraction trade-off and a win-rate funnel; none of them answered the
    question being asked, and each one was another thing to read past.
    """
    _style()
    directory.mkdir(parents=True, exist_ok=True)
    try:
        return [allocation_frontier(config, directory / "frontier.png")]
    except mix.AllocationLimit:
        return []
