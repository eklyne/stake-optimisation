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

from . import mix  # noqa: E402
from .config import Config  # noqa: E402

__all__ = ["write_all", "allocation_frontier"]

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#7a7972"
GRID = "#e8e7e4"

SERIES_BLUE = "#2a78d6"
STATUS_GOOD = "#0ca30c"

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


def allocation_frontier(config: Config, path: Path) -> Path:
    """Every way to split the tables, plotted as EUR/hour against risk.

    The cloud is every allocation; the line through its upper-left edge is the
    efficient frontier - the mixes nothing else beats on both axes. The best
    point inside tolerance is the answer, and the frontier's shape shows what
    each further step of risk actually buys.
    """
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
    return _finish(fig, path)


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
