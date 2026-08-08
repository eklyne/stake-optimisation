"""Charts. Five of them, written to PNG.

Palette note: these are the reference categorical/status/sequential values from
the data-viz design system, used verbatim rather than re-derived - the slot
ORDER is the colourblind-safety mechanism, so hues are assigned in fixed order by
stake size and never cycled. PNGs render on the light surface only; there is no
viewer theme to respond to.

Two rules worth naming because they shaped the charts rather than just decorating
them:

* No dual axis anywhere. The Kelly trade-off chart wants to show growth against
  drawdown risk, which are different units - so growth is plotted as a FRACTION
  of the full-Kelly rate, making both series unitless and sharing one axis.
* On the scatter, colour carries in/out of tolerance (a status, not an identity)
  and is always paired with a marker shape and a direct label, so it never has to
  be read by hue alone.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no display on this box; also keeps runs headless
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter, PercentFormatter  # noqa: E402

from . import estimation, kelly, mix, ruin  # noqa: E402
from .analysis import StakeReport  # noqa: E402
from .config import Config  # noqa: E402

__all__ = ["write_all"]

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#7a7972"
GRID = "#e8e7e4"

# Categorical slots, in the documented order. Assigned by stake size, never cycled.
SERIES = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948")
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
            "axes.titleweight": "semibold",
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


def _colour(index: int) -> str:
    return SERIES[index % len(SERIES)]


def _eur(value: float) -> str:
    if value >= 1_000_000:
        return f"EUR {value / 1_000_000:.1f}M"
    if value >= 10_000:
        return f"EUR {value / 1000:.0f}k"
    if value >= 1000:
        return f"EUR {value / 1000:.1f}k"
    return f"EUR {value:,.0f}"


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


# --------------------------------------------------------------------------- #
# 1. Risk of ruin against bankroll
# --------------------------------------------------------------------------- #
def ruin_vs_bankroll(reports: list[StakeReport], config: Config, path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(9, 5.5))

    # Frame the DECISION zone, not every stake. A 600NL curve that needs 20x the
    # current roll would otherwise squash the stakes actually in play into the
    # left margin - so the x-range is capped at the rolls within reach, and the
    # far-off curves simply exit the top of the plot.
    reachable = [
        r.bankroll_for_tolerance_eur
        for r in reports
        if r.bankroll_for_tolerance_eur and r.bankroll_for_tolerance_eur <= config.bankroll_eur * 6
    ]
    x_max = max([config.bankroll_eur * 2.0] + [n * 1.4 for n in reachable])
    xs = [x_max * i / 240.0 for i in range(1, 241)]

    # Identity is carried by the legend here: five curves that all converge on
    # the floor cannot take end-labels without collisions.
    for index, report in enumerate(reports):
        if report.winrate_eff <= 0:
            continue  # a losing stake is a flat line at 1.0; it says nothing
        ys = [
            max(
                ruin.risk_of_ruin(
                    report.winrate_eff, report.stdev_eff, x / report.stake.bb_eur
                ),
                RUIN_FLOOR,
            )
            for x in xs
        ]
        ax.plot(xs, ys, color=_colour(index), linewidth=2.0, label=report.stake.name)

    ax.axhline(config.ruin_tolerance, color=INK_MUTED, linewidth=1.2, linestyle="--")
    ax.annotate(
        f"your tolerance: {config.ruin_tolerance:.1%}",
        xy=(0, config.ruin_tolerance),
        xytext=(4, 5),
        textcoords="offset points",
        color=INK_MUTED,
        fontsize=9,
    )
    ax.axvline(config.bankroll_eur, color=INK_MUTED, linewidth=1.2, linestyle=":")
    ax.annotate(
        f"your roll: {_eur(config.bankroll_eur)}",
        xy=(config.bankroll_eur, 0.03),
        xycoords=("data", "axes fraction"),
        xytext=(5, 0),
        textcoords="offset points",
        color=INK_MUTED,
        fontsize=9,
    )

    ax.set_yscale("log")
    ax.set_ylim(RUIN_FLOOR, 1.0)
    ax.set_xlim(0, x_max)
    ax.set_xlabel("Bankroll (EUR)")
    ax.set_ylabel("Risk of ruin (log scale)")
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: _eur(v)))
    ax.grid(axis="y", alpha=0.9)
    ax.set_axisbelow(True)
    ax.set_title("Risk of ruin against bankroll")
    _subtitle(ax, "Where each curve crosses the dashed line is the roll that stake needs.")
    # Below the plot: every in-axes corner is occupied by a curve at some bankroll.
    ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.16),
        ncols=min(len(reports), 5),
    )
    return _finish(fig, path)


# --------------------------------------------------------------------------- #
# 2. The fractional-Kelly trade-off
# --------------------------------------------------------------------------- #
def kelly_tradeoff(config: Config, path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(9, 5.5))

    ks = [0.02 * i for i in range(1, 100)]  # 0.02 .. 1.98
    growth = [k * (2.0 - k) for k in ks]  # already a fraction of the full-Kelly rate
    drawdown = [kelly.rescaled_drawdown_probability(0.5, k) for k in ks]

    ax.plot(ks, growth, color=SERIES[0], linewidth=2.0, label="Growth rate (share of full Kelly)")
    ax.plot(ks, drawdown, color=SERIES[1], linewidth=2.0, label="P(ever losing half the roll)")

    for k, label in ((config.kelly_fraction, "your setting"), (1.0, "full Kelly")):
        ax.axvline(k, color=INK_MUTED, linewidth=1.0, linestyle=":")
        ax.annotate(
            f"{label} (k={k:g})",
            xy=(k, 1.02),
            xytext=(4, 0),
            textcoords="offset points",
            color=INK_MUTED,
            fontsize=9,
        )

    for k, series, colour in ((config.kelly_fraction, growth, SERIES[0]), (config.kelly_fraction, drawdown, SERIES[1])):
        value = series[min(range(len(ks)), key=lambda i: abs(ks[i] - k))]
        ax.plot([k], [value], marker="o", markersize=8, color=colour,
                markeredgecolor=SURFACE, markeredgewidth=2)
        ax.annotate(
            f"{value:.0%}",
            xy=(k, value),
            xytext=(8, -4),
            textcoords="offset points",
            color=colour,
            fontsize=9,
            fontweight="semibold",
        )

    ax.set_xlim(0, 2.0)
    ax.set_ylim(0, 1.12)
    ax.set_xlabel("Kelly fraction k (share of the growth-optimal exposure)")
    ax.set_ylabel("Share / probability")
    ax.yaxis.set_major_formatter(PercentFormatter(xmax=1.0))
    ax.grid(axis="y", alpha=0.9)
    ax.set_axisbelow(True)
    ax.set_title("Why nobody sane bets full Kelly")
    _subtitle(
        ax,
        "Growth peaks at k=1 and dies at k=2; drawdown risk keeps climbing. "
        "Underbetting is cheap, overbetting is not.",
    )
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), ncols=2)
    return _finish(fig, path)


# --------------------------------------------------------------------------- #
# 3. Required bankroll in buy-ins, against the conventions
# --------------------------------------------------------------------------- #
def required_buyins(reports: list[StakeReport], config: Config, path: Path) -> Path:
    usable = [r for r in reports if r.buyins_for_tolerance is not None]
    fig, ax = plt.subplots(figsize=(9, 5.5))

    if not usable:
        ax.set_title("Required bankroll in buy-ins")
        _subtitle(ax, "No stake has a positive win rate, so no finite bankroll is enough.")
        return _finish(fig, path)

    positions = list(range(len(usable)))
    width = 0.38
    tolerance_bars = [r.buyins_for_tolerance for r in usable]
    kelly_bars = [r.kelly_buyins if r.kelly_buyins is not None else 0.0 for r in usable]

    ax.bar([p - width / 2 - 0.01 for p in positions], tolerance_bars, width,
           color=SERIES[0], label=f"To hold ruin at {config.ruin_tolerance:.1%}")
    ax.bar([p + width / 2 + 0.01 for p in positions], kelly_bars, width,
           color=SERIES[1], label=f"Kelly at k={config.kelly_fraction:g}")

    for pos, value in zip(positions, tolerance_bars):
        ax.annotate(f"{value:.0f}", xy=(pos - width / 2 - 0.01, value), xytext=(0, 4),
                    textcoords="offset points", ha="center", fontsize=9, color=INK_SECONDARY)
    for pos, value in zip(positions, kelly_bars):
        ax.annotate(f"{value:.0f}", xy=(pos + width / 2 + 0.01, value), xytext=(0, 4),
                    textcoords="offset points", ha="center", fontsize=9, color=INK_SECONDARY)

    for convention in (20, 30, 50):
        ax.axhline(convention, color=INK_MUTED, linewidth=1.0, linestyle="--", alpha=0.7)
        # Labelled outside the plot area - inside, they land on whichever bar
        # happens to be tallest.
        ax.annotate(
            f"{convention} buy-ins",
            xy=(1.0, convention),
            xycoords=("axes fraction", "data"),
            xytext=(6, -3),
            textcoords="offset points",
            ha="left",
            color=INK_MUTED,
            fontsize=8.5,
        )

    ax.set_xticks(positions, [r.stake.name for r in usable])
    ax.set_ylabel("Buy-ins (100bb) required")
    ax.grid(axis="y", alpha=0.9)
    ax.set_axisbelow(True)
    ax.set_title("What each stake actually requires, against the folklore")
    _subtitle(
        ax,
        "The 20/30/50 buy-in conventions are a proxy for this calculation - "
        "sometimes a decent one, sometimes not.",
    )
    ax.legend(loc="upper left", ncols=2)
    return _finish(fig, path)


# --------------------------------------------------------------------------- #
# 4. Win-rate confidence funnel
# --------------------------------------------------------------------------- #
def winrate_funnel(reports: list[StakeReport], path: Path) -> Path:
    """Small multiples - one panel per stake.

    Overlaid, five confidence bands cover each other almost completely and the
    chart says nothing. Faceting is the standard escape: the panels share axes,
    so the widths stay directly comparable, which is the whole comparison being
    made.
    """
    played = [r.stake.hands for r in reports if r.stake.hands]
    x_max = max([400_000] + [h * 3 for h in played])
    xs = [10_000 * (x_max / 10_000) ** (i / 120.0) for i in range(121)]

    columns = min(len(reports), 3)
    rows = -(-len(reports) // columns)
    fig, axes = plt.subplots(
        rows, columns, figsize=(3.3 * columns, 2.9 * rows), sharex=True, sharey=True,
        squeeze=False,
    )
    flat = [ax for row in axes for ax in row]

    bands = [
        [estimation.winrate_ci(r.winrate_eff, r.stdev_eff, int(h)) for h in xs] for r in reports
    ]
    y_low = min(low for band in bands for low, _ in band)
    y_high = max(high for band in bands for _, high in band)

    for index, (report, band, ax) in enumerate(zip(reports, bands, flat)):
        colour = _colour(index)
        ax.fill_between(
            xs, [low for low, _ in band], [high for _, high in band],
            color=colour, alpha=0.20, linewidth=0,
        )
        ax.axhline(report.winrate_eff, color=colour, linewidth=1.8)
        ax.axhline(0, color=INK_MUTED, linewidth=1.0)
        if report.stake.hands:
            ax.plot([report.stake.hands], [report.winrate_eff], marker="o", markersize=8,
                    color=colour, markeredgecolor=SURFACE, markeredgewidth=2)
            low, high = estimation.winrate_ci(
                report.winrate_eff, report.stdev_eff, report.stake.hands
            )
            note = f"{report.stake.hands / 1000:.0f}k hands: {low:.1f} to {high:.1f}"
        else:
            note = "no hand count given"
        ax.set_title(report.stake.name, color=colour, fontsize=11, pad=18)
        ax.annotate(
            note, xy=(0, 1.0), xycoords="axes fraction", xytext=(0, 5),
            textcoords="offset points", fontsize=8.5, color=INK_SECONDARY, va="bottom",
        )
        ax.set_xscale("log")
        ax.set_xlim(10_000, x_max)
        ax.set_ylim(y_low, y_high)
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v / 1000:.0f}k"))
        ax.grid(axis="y", alpha=0.9)
        ax.set_axisbelow(True)

    for ax in flat[len(reports):]:
        ax.set_visible(False)

    fig.supxlabel("Hands played (log scale)", color=INK_SECONDARY, fontsize=10)
    fig.supylabel("Win rate (bb/100), 95% interval", color=INK_SECONDARY, fontsize=10)
    fig.suptitle(
        "How much of your win rate is actually known",
        x=0.01, y=0.995, ha="left", va="top",
        fontsize=13, fontweight="semibold", color=INK,
    )
    fig.text(
        0.01, 0.945,
        "The dot marks the volume you have. The band is everything the sample still permits.",
        ha="left", va="top", fontsize=9.5, color=INK_SECONDARY,
    )
    fig.tight_layout(rect=(0.01, 0.0, 1.0, 0.90))
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


# --------------------------------------------------------------------------- #
# 5. The two-covariate plane
# --------------------------------------------------------------------------- #
def ev_vs_risk(reports: list[StakeReport], config: Config, path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(9, 5.5))

    x_low, x_high = RUIN_FLOOR / 3.0, 3.0
    midpoint = (x_low * x_high) ** 0.5  # geometric, because the axis is log

    for report in reports:
        x = max(report.risk_of_ruin, RUIN_FLOOR)
        inside = report.within_tolerance
        ax.plot(
            [x],
            [report.eur_per_hour],
            marker="o" if inside else "X",
            markersize=12 if inside else 11,
            color=STATUS_GOOD if inside else STATUS_CRITICAL,
            markeredgecolor=SURFACE,
            markeredgewidth=2,
            linestyle="none",
        )
        # Flip the label inboard on the right-hand half, or it runs off the plot.
        on_the_right = x > midpoint
        ax.annotate(
            f"{report.stake.name}\n{report.eur_per_hour:,.0f} EUR/hr",
            xy=(x, report.eur_per_hour),
            xytext=(-12 if on_the_right else 12, -4),
            textcoords="offset points",
            ha="right" if on_the_right else "left",
            color=INK,
            fontsize=9,
            fontweight="semibold",
        )

    ax.axvline(config.ruin_tolerance, color=INK_MUTED, linewidth=1.2, linestyle="--")
    ax.annotate(
        f"tolerance {config.ruin_tolerance:.1%}",
        xy=(config.ruin_tolerance, 1.0),
        xycoords=("data", "axes fraction"),
        xytext=(-6, -14),
        textcoords="offset points",
        ha="right",
        color=INK_MUTED,
        fontsize=9,
    )

    ax.set_xscale("log")
    ax.set_xlim(x_low, x_high)
    ax.margins(y=0.18)
    ax.set_xlabel("Risk of ruin at your current bankroll (log scale)")
    ax.set_ylabel("EUR / hour")
    ax.grid(alpha=0.9)
    ax.set_axisbelow(True)
    ax.set_title("The whole decision, on two axes")
    _subtitle(ax, "Take the highest point that sits left of the dashed line.")
    ax.legend(
        handles=[
            plt.Line2D([], [], marker="o", linestyle="none", markersize=10,
                       color=STATUS_GOOD, label="Inside tolerance"),
            plt.Line2D([], [], marker="X", linestyle="none", markersize=10,
                       color=STATUS_CRITICAL, label="Outside tolerance"),
        ],
        loc="upper left",
    )
    return _finish(fig, path)


# --------------------------------------------------------------------------- #
# 6. The efficient frontier over table allocations
# --------------------------------------------------------------------------- #
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
        color=SERIES[0], linewidth=2.0, marker="o", markersize=5,
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
            color=INK, fontsize=9.5, fontweight="semibold",
        )

    ax.set_xscale("log")
    ax.set_xlim(RUIN_FLOOR / 3.0, 3.0)
    ax.margins(y=0.15)
    ax.set_xlabel("Risk of ruin (log scale)")
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


def write_all(reports: list[StakeReport], config: Config, directory: Path) -> list[Path]:
    """Render all six charts into `directory`, returning the paths written."""
    _style()
    directory.mkdir(parents=True, exist_ok=True)
    paths = [
        ruin_vs_bankroll(reports, config, directory / "01_ruin_vs_bankroll.png"),
        kelly_tradeoff(config, directory / "02_kelly_tradeoff.png"),
        required_buyins(reports, config, directory / "03_required_buyins.png"),
        winrate_funnel(reports, directory / "04_winrate_funnel.png"),
        ev_vs_risk(reports, config, directory / "05_ev_vs_risk.png"),
    ]
    try:
        paths.append(allocation_frontier(config, directory / "06_allocation_frontier.png"))
    except mix.AllocationLimit:
        pass  # too many allocations to enumerate; the other five still stand
    return paths
