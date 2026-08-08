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


def simulation_figure(result, config: Config):
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
    left.set_title("Where the bankroll ends up")
    # Kept short: two subtitles sit side by side and a long one runs into its
    # neighbour's panel.
    _subtitle(left, "Bands: 5-95 and 25-75 percentiles. Grey: six lifetimes, by finish.")

    # Clip the tail: a handful of extreme lifetimes otherwise stretch the axis to
    # four times the interesting range and squash the whole distribution left.
    x_max = float(np.percentile(result.max_drawdown, 99.5))
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
