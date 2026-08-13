"""The frontier charts.

TWO charts of the same trade-off, because there are two ways to say how much risk
is too much (see `tolerance.py`) and the picture should show the one that actually
bound. Both plot EUR/hour up the y-axis against a risk measure across the x:

* `allocation_frontier_figure` - x is risk of ruin, all-time, log scale. Every
  allocation is on it, because the measure is analytic and free.
* `allocation_frontier_downswing_figure` - x is the peak-to-trough downswing you
  run at probability p over a stated horizon, in money, linear. Only the CANDIDATES
  are on it: each point costs a simulation, so plotting the full cloud would mean
  thousands of them.

Whichever mode is configured, both are drawn - the second view is worth having
either way - but only the active rule gets a tolerance line, so the chart never
implies a constraint that was not applied.

Colours come from the deck template's own theme palette (see the ACCENT_*
constants), so a chart dropped on a slide sits in the same palette as everything
around it. The charts render on the light surface only, since a PNG has no viewer
theme to respond to. Colour carries in/out of tolerance - a status, not an
identity - and is always paired with a shape and, on the standalone PNGs, a direct
label, so it never has to be read by hue alone.

Money is drawn in the display currency (`config.currency`), converted at the point
of labelling. The values behind the points stay euros.
"""

from __future__ import annotations

import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no display on this box; also keeps runs headless
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter, MaxNLocator  # noqa: E402

from . import mix  # noqa: E402
from .ruin import odds_against as _odds  # noqa: E402
from .config import Config  # noqa: E402

__all__ = [
    "write_all",
    "allocation_frontier",
    "allocation_frontier_figure",
    "allocation_frontier_downswing_figure",
    "frontier_pair_figure",
    "frontier_notes",
    "ruin_subtitle",
    "downswing_subtitle",
    "simulation_figure",
    "lifetimes_figure",
    "simulation_notes",
    "simulation_scales",
    "winrate_ci_figure",
]

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#7a7972"
GRID = "#e8e7e4"

# ---- The deck template's own theme palette -------------------------------- #
# Read out of assets/deck_template.pptx (ppt/theme/theme1.xml, a:clrScheme) and
# pinned here as literals rather than parsed at draw time: the charts have to
# render with no template on disk (a fresh clone does not have it - it is a
# personal asset and gitignored), and a chart palette that silently changed with
# a file the repo does not ship would be worse than one that needs a re-copy.
# Re-read them if the template's theme is ever edited.
ACCENT_BLUE = "#24658d"     # accent1
ACCENT_GREEN = "#388968"    # accent2
ACCENT_DARK_RED = "#9d0208"  # accent3
ACCENT_ORANGE = "#e85d04"   # accent4
ACCENT_PURPLE = "#632a7e"   # accent5
ACCENT_PINK = "#e05780"     # accent6

SERIES_BLUE = ACCENT_BLUE
STATUS_GOOD = ACCENT_GREEN
STATUS_CRITICAL = ACCENT_DARK_RED
"""Reserved for genuine danger - the ruin barrier, and nothing else."""

COL_CURRENT = ACCENT_PINK
"""The mix currently played, on the SIMULATION charts. Pink, deliberately NOT the
red used for ruin: the current mix is a reference point, not a warning, and
drawing it in the danger colour made every deck read as though it were an
emergency."""

COL_CURRENT_MARK = "#4c9fd1"
"""The current mix ON THE FRONTIER CHARTS specifically - a blue circle, the same
size and shape as the green 'best' circle, so the two read as two values of one
thing (where you are / where you could be) rather than as two different objects.
The pink diamond above still marks it on the simulation charts, where there is no
paired 'best' marker to match.

The theme blue LIGHTENED - same hue and saturation as `ACCENT_BLUE`, lifted from
0.35 luminance to 0.56. At full strength it and the theme green are both dark
mid-tones, and at 10pt with a grey ring the two circles were hard to tell apart
at slide distance. Lightening one separates them by value as well as by hue,
which is also what makes the pair survive a greyscale print."""

TINT_GREEN = "#7fc0a4"
TINT_BLUE = "#7db9de"
"""Pale versions of the two mix colours, for the MASS around a mix rather than
the mix itself: the frontier it is drawn from, the percentile bands it lives
inside, the individual lifetimes it averages over.

Both are the accent hue at raised luminance, so a panel of pale-green spaghetti
under a solid-green EV line reads as one family, and the green panel and the blue
panel stay tellable apart at a glance."""

COL_FRONTIER = TINT_GREEN
"""The efficient frontier line - the theme green, tinted about 35% toward white.

Same hue as the chosen point on purpose: the frontier is the SET that point is
drawn from. Lighter keeps the single dark-green answer the thing the eye lands
on, and keeps a two-pixel line legible against the grey cloud behind it."""

COL_PATHS = INK_SECONDARY
"""The individual simulated lifetimes. Darker than `INK_MUTED`, which is the grey
for things that should recede (the dominated cloud, axis furniture): a lifetime is
meant to be followed with the eye from left to right, and at 0.6pt the muted grey
faded out against the band behind it."""

MARK_EDGE = "#6f6e6a"
"""The outline on the two answer markers. A mid grey, not the surface colour: a
white ring reads as a gap in the line the marker sits on, and on the frontier
that gap lands exactly where the eye is trying to follow the curve."""

COL_RUIN_LIMIT = ACCENT_DARK_RED
COL_DOWNSWING_LIMIT = ACCENT_ORANGE
"""The two risk bars, told apart by COLOUR ALONE - same weight, same dash.

They used to differ in dash pattern as well, encoding threshold-versus-cut. That
distinction is real (see `_cut_point`) but it is a property of which chart you are
looking at, not of the bar, and drawing two dash patterns per panel made the pair
slide read as four different kinds of line. It is said in words on the slide
instead."""

RUIN_NEGLIGIBLE = 1e-6
"""Below this, a lifetime risk of ruin is not a decision anyone makes.

Used only to decide whether the ruin axis has ANYTHING to say: if every mix is
under it, the chart gives up on ranking by ruin and shows the earnings spread
instead (`_ruin_cannot_rank_figure`). It is deliberately NOT the plotting floor -
that job is a different one, see below."""

FLOOR_DECADES = 12
"""How many orders of magnitude of ruin the x-axis shows before clamping.

The floor has to exist: the safest mixes run to 1e-129, and an axis spanning 123
decades squashes every mix anyone would actually consider into the last few
pixels. But it should not be a CONSTANT. A fixed 1e-6 was calibrated for one
bankroll, and on a healthy roll it piled an eighth of the mixes onto the left
edge - including, on the shipped config, both the chosen mix and the downswing
cut line, so the chart could not show where either really sat.

Twelve decades below the riskiest mix keeps the structure visible (about 3% of
mixes clamped rather than 12%) while still cutting the meaningless tail, and it
follows the data instead of needing re-tuning per bankroll."""


def ruin_floor(allocations) -> float:
    """The plotting floor for this particular set of mixes."""
    risks = [a.risk_of_ruin for a in allocations if a.risk_of_ruin > 0]
    if not risks:
        return RUIN_NEGLIGIBLE
    return max(risks) / (10.0 ** FLOOR_DECADES)


def _style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "savefig.facecolor": SURFACE,
            # Axis furniture is BLACK - spines, ticks, tick labels, axis titles,
            # legend text. It used to be grey on grey (#52514e text, #e8e7e4
            # spines), which reads as a faded screenshot once the chart is on a
            # slide at arm's length. Only the GRID stays pale: it is the one
            # element that has to sit behind the data without competing with it.
            "axes.edgecolor": INK,
            "axes.linewidth": 1.0,
            "axes.labelcolor": INK,
            "axes.titlecolor": INK,
            "axes.titlesize": 13,
            "axes.titleweight": "bold",
            "axes.titlelocation": "left",
            "axes.titlepad": 30,  # leaves room for the subtitle line beneath it
            "axes.labelsize": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "xtick.color": INK,
            "ytick.color": INK,
            "xtick.labelcolor": INK,
            "ytick.labelcolor": INK,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "grid.color": GRID,
            "grid.linewidth": 0.8,
            "legend.frameon": False,
            "legend.fontsize": 9,
            "legend.labelcolor": INK,
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


def _tolerance_line(
    ax, x: float, label: str, colour: str,
    y: float = 0.02, legend: str | None = None, annotate: bool = True,
) -> None:
    """A limit drawn on the axis, by a rule that was actually applied.

    Every bar is drawn the same way - same weight, same dash - and told apart by
    COLOUR, with `legend` naming it in the key. Whether a given line is this
    axis's own threshold or the OTHER rule's cut point (see `_cut_point`) is said
    in the legend wording ('bites here') and in the slide's notes, not in the dash
    pattern: that is a fact about which chart you are looking at, and encoding it
    in the stroke made a two-panel slide look like it had four kinds of line on it.

    `y` staggers the labels: with both rules in play the two lines can be close
    together, and their labels point INWARD at each other across the gap.

    `annotate=False` draws the line without its on-chart label, for the deck,
    where the same wording is carried by the legend and the slide's own text.
    """
    ax.axvline(
        x, color=colour, linewidth=1.6, linestyle="--", label=legend,
    )
    if not annotate:
        return
    # A limit hard against the left edge - which is where the stricter of two
    # rules lands - would otherwise have its label written off the canvas.
    near_left = _axis_fraction(ax, x) < 0.30
    ax.annotate(
        label,
        xy=(x, y), xycoords=("data", "axes fraction"),
        xytext=(6, 0) if near_left else (-6, 0), textcoords="offset points",
        ha="left" if near_left else "right",
        color=colour, fontsize=9, fontweight="bold",
    )


def _cut_point(ordered, admits, position, log_axis: bool = False):
    """Where along `ordered` a rule stops admitting, in axis units.

    The honest way to put ONE rule's limit on the OTHER rule's axis. A downswing
    limit is not a threshold in risk-of-ruin - it is a different function of the
    allocation, so the admissible set need not be a half-line in x at all. What
    it usually IS, along a frontier ordered by risk, is a single crossing: both
    measures climb with variance and fall with mean, so admissible mixes sit at
    one end and rejected ones at the other.

    So: verify that crossing empirically rather than assuming it. Returns the
    position of a SINGLE clean flip, or None when the rule never bites on this
    axis, or when it bites in more than one place - in which case no line is
    drawn, because a line would claim a boundary that is not there.

    `ordered` must already be sorted along the axis. On a log axis the crossing
    is placed at the geometric midpoint, which is the visual middle there.
    """
    verdicts = [admits(item) for item in ordered]
    if not verdicts or all(verdicts) or not any(verdicts):
        return None
    flips = [i for i in range(1, len(verdicts)) if verdicts[i] != verdicts[i - 1]]
    if len(flips) != 1:
        return None
    index = flips[0]
    low, high = position(ordered[index - 1]), position(ordered[index])
    if log_axis:
        if low <= 0 or high <= 0:
            return high
        return math.sqrt(low * high)
    return (low + high) / 2.0


def _hourly(eur_per_hour: float, config: Config) -> str:
    return f"{config.currency.fmt(eur_per_hour)}/hr"


def _thousands(value, _=None) -> str:
    """Money tick labels, abbreviated: 8,000 -> 8k.

    Full labels with a thousands separator are wide enough that four of them
    collide in a half-width panel, which reads as a smear rather than an axis.
    """
    if abs(value) >= 1000:
        return f"{value / 1000:,.0f}k"
    return f"{value:,.0f}"


def _axis_fraction(ax, x: float) -> float:
    """Where `x` falls across the axis, 0 at the left edge and 1 at the right.

    Goes through the axis transform, so it is correct under a log scale as well
    as a linear one - the limits alone are not enough to work this out.
    """
    y = sum(ax.get_ylim()) / 2.0  # any point on the axis; only the x is read back
    return float(ax.transAxes.inverted().transform(ax.transData.transform((x, y)))[0])


def _mark_best(ax, x: float, best, config: Config, annotate: bool = True) -> None:
    """The chosen mix, marked identically on both frontier charts.

    Same shape, colour and label wording on each, so the two read as one pair and
    the eye can carry the answer from one picture to the other.

    `x` arrives already in whatever units its axis is drawn in; the y value is
    converted here, because it is always money and always comes off the
    allocation in euros.

    `annotate=False` leaves the marker but drops its block of text - the deck
    prints the same numbers beside the chart, where they cannot land on top of
    the cloud (see `frontier_notes`).
    """
    y = config.currency.from_eur(best.eur_per_hour)
    ax.plot(
        [x], [y],
        marker="o", markersize=10, color=STATUS_GOOD,
        markeredgecolor=MARK_EDGE, markeredgewidth=1.0, linestyle="none",
        label="Best inside tolerance",
    )
    if not annotate:
        return
    # The chosen mix often sits at the far left - it is the safe end of the
    # frontier - and a right-aligned label there runs off the canvas. Flip it to
    # the other side of the marker when it is close to the edge. Measured through
    # the axis transform rather than by arithmetic on the limits, so it is right
    # on the log-scaled ruin axis as well as the linear downswing one.
    near_left = _axis_fraction(ax, x) < 0.25
    ax.annotate(
        # Money, exposure and risk together: what it pays, what is on the table
        # to make that, and the odds against it ending badly.
        f"{best.label}\n{_hourly(best.eur_per_hour, config)}"
        f"  |  {config.currency.fmt(best.exposure_eur)} on tables"
        f"\nruin {_odds(best.risk_of_ruin)}",
        xy=(x, y),
        xytext=(14, 6) if near_left else (-14, 6), textcoords="offset points",
        ha="left" if near_left else "right",
        color=INK, fontsize=9.5, fontweight="bold",
    )


def _mark_current(ax, x: float, current, config: Config, annotate: bool = True) -> None:
    """The mix actually being played, so the gap to the frontier is visible rather
    than described. Vertical distance to the frontier is EV left on the table;
    horizontal distance is risk taken for nothing.

    Same circle, same size as `_mark_best` - only the colour differs. The two
    markers are the same KIND of thing (a mix, at a point on this trade-off), and
    giving them different shapes made them read as different quantities.
    """
    y = config.currency.from_eur(current.eur_per_hour)
    ax.plot(
        [x], [y],
        marker="o", markersize=10, color=COL_CURRENT_MARK,
        markeredgecolor=MARK_EDGE, markeredgewidth=1.0, linestyle="none",
        label="What you are playing now",
    )
    if not annotate:
        return
    ax.annotate(
        f"current: {_hourly(current.eur_per_hour, config)}  |  "
        f"ruin {_odds(current.risk_of_ruin)}",
        xy=(x, y),
        xytext=(10, -14), textcoords="offset points",
        color=COL_CURRENT_MARK, fontsize=9.5, fontweight="bold",
    )


def _downswing_cut_on_ruin_axis(config: Config, edge, floor: float):
    """Where the downswing rule stops admitting, in risk-of-ruin units.

    Walked along the ruin frontier, which is the ordering the axis is drawn in.
    Two things keep it affordable next to a chart that is otherwise free:

    * the analytic floor (`DownswingTolerance.floor`) rejects the bold end for
      nothing at all - a third of the frontier, here;
    * survivors are judged at `sim.SCREEN_PATHS`, not the full verdict count.
      This is a guide line on a picture, not the verdict that picks your mix, and
      a few hundred paths put the crossing in the right place.
    """
    from . import sim, tolerance as _tolerance

    rule = _tolerance.DownswingTolerance()
    limit = config.downswing_amount_eur
    if limit is None:
        return None

    def admits(allocation):
        if allocation.mean_eur_per_100 <= 0:
            return False
        floor = rule.floor(allocation, config)
        if floor is not None and floor > limit:
            return False
        return sim.drawdown_quantile(
            config, allocation, hands=config.downswing_hands,
            quantile=1.0 - config.downswing_probability, paths=sim.SCREEN_PATHS,
        ) <= limit

    return _cut_point(
        edge, admits, lambda a: max(a.risk_of_ruin, floor), log_axis=True
    )


def _one_in(probability: float) -> str:
    """A tiny probability as odds, rounded to something sayable.

    "1 in 21 billion", not "one chance in 21,399,231,025" - the digits past the
    first are noise, and printing them implies a precision the model has not got.
    """
    if probability <= 0:
        return "effectively zero"
    odds = 1.0 / probability
    for limit, suffix in ((1e12, "trillion"), (1e9, "billion"), (1e6, "million")):
        if odds >= limit:
            return f"1 in {odds / limit:,.0f} {suffix}"
    return f"1 in {odds:,.0f}"


def _ruin_cannot_rank_draw(ax, config: Config, allocations, best, current,
                           annotate=True, legend=True):
    """What the ruin chart becomes when no mix carries meaningful ruin.

    Replaces the scatter with the earnings range and a plain statement, because
    at this bankroll the honest content of the chart is one sentence: risk of
    ruin does not distinguish any of these, so it cannot choose between them.
    The reader is pointed at the axis that can.
    """
    import numpy as np

    money = config.currency.from_eur
    hourly = [money(a.eur_per_hour) for a in allocations]
    worst = max(a.risk_of_ruin for a in allocations)

    # The mixes are still spread along the EARNINGS axis, so that is what gets
    # drawn - one mark per mix, stacked where they pile up. The reader still sees
    # what is on offer and how thickly the options cluster; the only thing
    # withheld is the risk ranking, which does not exist here.
    counts, edges = np.histogram(hourly, bins=36)
    ax.bar(
        (edges[:-1] + edges[1:]) / 2, counts, width=(edges[1] - edges[0]) * 0.9,
        color=SERIES_BLUE, alpha=0.55, linewidth=0, label="Every possible mix",
    )

    # `vlines`, not `axvline`: an axvline spans the whole axes whatever the
    # margins are, so it would be drawn straight through the note above.
    head = counts.max() * 1.04
    for allocation, colour, marker, label in (
        (best, STATUS_GOOD, "o", "Chosen"),
        (current, STATUS_CRITICAL, "D", "What you are playing now"),
    ):
        if allocation is None:
            continue
        at = money(allocation.eur_per_hour)
        ax.vlines(at, 0, head, color=colour, linewidth=1.6)
        ax.plot([at], [head], marker=marker, markersize=11, color=colour,
                markeredgecolor=SURFACE, markeredgewidth=2, linestyle="none",
                label=label)

    ax.set_xlabel(config.currency.axis("/ hour"))
    ax.set_ylabel("Number of mixes")
    ax.xaxis.set_major_formatter(FuncFormatter(_thousands))
    # Enough headroom that the note below clears the marker row entirely. The two
    # marker lines run the full height of the bars, so anything sharing that band
    # gets a vertical rule drawn through it.
    ax.margins(y=0.34)  # headroom for the note; the floor is pinned below
    ax.set_ylim(bottom=0)
    ax.grid(axis="y", alpha=0.9)
    ax.set_axisbelow(True)
    if annotate:
        ax.set_title(f"Every way to split {config.tables} tables across your stakes")
        _subtitle(ax, _cannot_rank_subtitle(allocations, worst))
        # Top LEFT: the chosen mix is the best-earning one, so it and its marker
        # sit at the right-hand end of this axis by construction, and a note over
        # there lands on top of them.
        ax.annotate(
            f"On a {config.currency.fmt(config.bankroll_eur)} bankroll ruin is not the "
            f"binding constraint,\nso this is the earnings spread instead. What separates "
            f"these mixes\nis how deep a downswing they put you through - the next chart.",
            xy=(0.02, 0.97), xycoords="axes fraction", ha="left", va="top",
            fontsize=9.5, color=INK_SECONDARY,
        )
    if legend:
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncols=3)


def _cannot_rank_subtitle(allocations, worst: float) -> str:
    return (
        f"Ruin cannot rank these: all {len(allocations):,} sit under "
        f"{RUIN_NEGLIGIBLE:g}, the riskiest at {_one_in(worst)}."
    )


def allocation_frontier_figure(config: Config, annotate: bool = True):
    """Every way to split the tables, plotted as EUR/hour against risk.

    The cloud is every allocation; the line through its upper-left edge is the
    efficient frontier - the mixes nothing else beats on both axes. The best
    point inside tolerance is the answer, and the frontier's shape shows what
    each further step of risk actually buys.

    Returns the figure so the deck can embed it as vector-quality output rather
    than re-reading a rendered PNG.

    `annotate=False` strips the title, subtitle and every direct label, leaving
    the marks, the axes and the key. That is the DECK's version: the slide has
    its own title and prints the same wording as text beside the picture, so
    on-chart copy is duplication that also sits on top of the data. The standalone
    PNG keeps its labels, since nothing else carries them there.
    """
    _style()
    fig, ax = plt.subplots(figsize=(9.5, 6))
    _draw_allocation_frontier(ax, config, annotate=annotate)
    fig.tight_layout()
    return fig


def _draw_allocation_frontier(
    ax, config: Config, annotate: bool = True, legend: bool = True,
) -> None:
    """Draw the ruin frontier onto an existing axes - see the figure wrapper.

    `legend=False` leaves the marks labelled but draws no key, for the two-panel
    figure, which carries one shared key for both (`_pair_legend`)."""
    allocations = mix.all_allocations(config)
    edge = mix.frontier(allocations)
    best = mix.best_allocation(allocations, config)
    # The mix actually being played, so the gap to the frontier is visible rather
    # than described. Its vertical distance to the blue line is EV left on the
    # table; its horizontal distance is risk taken for nothing.
    current = mix.current_allocation(config)

    # y is money, so it is DRAWN in the display currency - the axis label says so.
    # Converting only the label would leave a chart reading "GBP" over euro values.
    money = config.currency.from_eur

    # At a large enough bankroll EVERY mix falls under the floor, and the chart
    # degenerates into a vertical stick of points stacked on the left edge. That
    # is not a rendering problem to be scaled away - it is the finding, and it
    # needs saying rather than drawing. Autoscaling to the data would be worse:
    # the spread here runs eighty-odd decades, and separating 1e-97 from 1e-11 on
    # an axis invites reading a difference between two numbers that are both
    # zero for every human purpose.
    if allocations and max(a.risk_of_ruin for a in allocations) < RUIN_NEGLIGIBLE:
        return _ruin_cannot_rank_draw(
            ax, config, allocations, best, current, annotate=annotate, legend=legend
        )

    # Follows the data rather than a constant: twelve decades below the riskiest
    # mix on this ladder. See FLOOR_DECADES.
    floor = ruin_floor(allocations)

    ax.scatter(
        [max(a.risk_of_ruin, floor) for a in allocations],
        [money(a.eur_per_hour) for a in allocations],
        s=5, color=INK_MUTED, alpha=0.32, linewidths=0, label="Every possible mix",
    )
    ax.plot(
        [max(a.risk_of_ruin, floor) for a in edge],
        [money(a.eur_per_hour) for a in edge],
        color=COL_FRONTIER, linewidth=2.0, marker="o", markersize=4.5,
        markeredgewidth=0, label="Efficient frontier",
    )

    # Scale and limits BEFORE the markers: `_mark_best` decides which side of the
    # point to put its label on by where the point falls in the axis, so an axis
    # still carrying autoscaled linear limits would give it the wrong answer.
    ax.set_xscale("log")
    ax.set_xlim(floor / 3.0, 3.0)
    ax.margins(y=0.15)

    # Each rule draws only if it was actually applied - a line for a constraint
    # that did not run would be a claim about the answer that is not true.
    if config.risk_mode in ("ruin", "both"):
        _tolerance_line(
            ax, config.ruin_tolerance,
            f"ruin {_odds(config.ruin_tolerance)}",
            COL_RUIN_LIMIT,
            legend=f"Ruin bar ({_odds(config.ruin_tolerance)})",
            annotate=annotate,
        )
    if config.risk_mode in ("downswing", "both"):
        cut = _downswing_cut_on_ruin_axis(config, edge, floor)
        if cut is not None:
            _tolerance_line(
                ax, cut,
                f"downswing {config.currency.fmt(config.downswing_amount_eur)}",
                COL_DOWNSWING_LIMIT, y=0.10,
                legend=f"Downswing bar bites here "
                       f"({config.currency.fmt(config.downswing_amount_eur)})",
                annotate=annotate,
            )

    if best is not None:
        _mark_best(ax, max(best.risk_of_ruin, floor), best, config, annotate=annotate)

    if current is not None:
        _mark_current(
            ax, max(current.risk_of_ruin, floor), current, config, annotate=annotate
        )
    # Any stack remaining on the left edge is the floor, not a coincidence: those
    # mixes carry a risk too small to tell apart or to care about.
    ax.set_xlabel(
        f"Risk of ruin (log scale; under {floor:.0e} is drawn at the floor)"
    )
    ax.set_ylabel(config.currency.axis("/ hour"))
    ax.grid(alpha=0.9)
    ax.set_axisbelow(True)
    if annotate:
        ax.set_title(f"Every way to split {config.tables} tables across your stakes")
        _subtitle(ax, ruin_subtitle(config))
    if legend:
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncols=3)


def ruin_subtitle(config: Config) -> str:
    """How to read the ruin chart. Public because the deck prints it as slide
    text instead of drawing it into the picture."""
    return {
        "ruin": "Take the highest point left of the red line. The frontier is the "
                "menu; everything below it is dominated.",
        "downswing": "Ruin is shown for reference - the downswing rule chose the "
                     "answer. The orange line is where that rule bites.",
        "both": "Red is the ruin bar, orange is where the downswing bar bites. The "
                "answer must clear both, so the leftmost line binds.",
    }[config.risk_mode]


def allocation_frontier(config: Config, path: Path) -> Path:
    """Render the frontier chart to `path`."""
    fig = allocation_frontier_figure(config)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def allocation_frontier_downswing_figure(config: Config, annotate: bool = True):
    """The same trade-off, priced in the downswing you would actually live through.

    x is the peak-to-trough fall this mix reaches at probability p within the
    configured horizon - so a point at 4,000 means "one stretch in twenty contains
    a fall of 4,000 or worse". Linear, and in money, because unlike a ruin
    probability it is a quantity you can hold next to your bankroll.

    **Only candidates are plotted, not every mix.** Each point is a simulation, so
    the cloud of a thousand-odd allocations is out of reach; what is drawn is the
    ruin frontier, the mixes the optimiser actually tested on its way to an answer
    (already cached, so free), and the chosen and current mixes. Those are the ones
    with anything to say. The line through them is the subset nothing else beats on
    both axes - a frontier over the candidates, which is why it is labelled that
    way rather than as THE frontier.

    `annotate=False` is the deck's version - see `allocation_frontier_figure`.
    """
    _style()
    fig, ax = plt.subplots(figsize=(9.5, 6))
    _draw_downswing_frontier(ax, config, annotate=annotate)
    fig.tight_layout()
    return fig


def _draw_downswing_frontier(
    ax, config: Config, annotate: bool = True, legend: bool = True,
) -> None:
    """Draw the downswing frontier onto an existing axes - see the wrapper."""
    from . import tolerance as _tolerance

    rule = _tolerance.DownswingTolerance()
    allocations = mix.all_allocations(config)
    best = mix.best_allocation(allocations, config)
    current = mix.current_allocation(config)

    # Deduplicated on the mix, then measured. Anything the optimiser already
    # tested comes straight back out of the simulation cache.
    candidates: dict[tuple[int, ...], object] = {a.counts: a for a in mix.frontier(allocations)}
    for extra in (best, current):
        if extra is not None:
            candidates[extra.counts] = extra

    points = []
    for allocation in candidates.values():
        # A losing mix has no bounded drawdown to plot - it simply descends - and
        # `rule.measure` would be reporting the horizon, not the risk.
        if allocation.mean_eur_per_100 <= 0:
            continue
        points.append((rule.measure(allocation, config), allocation))
    if not points:
        ax.set_axis_off()
        ax.annotate(
            "No mix in this configuration makes money, so there is no\n"
            "downswing distribution to draw.",
            xy=(0.5, 0.5), xycoords="axes fraction", ha="center", va="center",
            color=INK_SECONDARY, fontsize=11,
        )
        return

    points.sort(key=lambda pair: pair[0])
    # Both axes are money, so both are DRAWN in the display currency. Plotting
    # euros under a converted tick formatter would leave the axis ticking at
    # euro round numbers relabelled into ragged sterling ones.
    money = config.currency.from_eur
    measured = {allocation.counts: money(value) for value, allocation in points}

    ax.scatter(
        [money(value) for value, _ in points],
        [money(allocation.eur_per_hour) for _, allocation in points],
        s=10, color=INK_MUTED, alpha=0.5, linewidths=0, label="Frontier candidates",
    )

    # Undominated on THIS axis: cheapest downswing for the money, walking left to
    # right and keeping anything that pays more than everything safer than it.
    edge, best_so_far = [], float("-inf")
    for value, allocation in points:
        if allocation.eur_per_hour > best_so_far:
            edge.append((value, allocation))
            best_so_far = allocation.eur_per_hour
    ax.plot(
        [money(value) for value, _ in edge],
        [money(allocation.eur_per_hour) for _, allocation in edge],
        color=COL_FRONTIER, linewidth=2.0, marker="o", markersize=4.5,
        markeredgewidth=0, label="Efficient over these",
    )

    # Margins BEFORE anything that measures the axis. `_tolerance_line` and
    # `_mark_best` both decide which side of a point to write their label on by
    # where it falls across the axis, and an axis still autoscaling gives them a
    # different answer from the one the reader ends up seeing.
    ax.margins(x=0.10, y=0.15)
    ax.autoscale_view()
    # A downswing of less than nothing is not a thing, so the axis starts at zero
    # rather than at whatever the left margin worked out to. Set AFTER the margin
    # call (which would otherwise re-open the gap) and BEFORE anything that
    # measures the axis to place a label.
    ax.set_xlim(left=0)

    if config.risk_mode in ("downswing", "both"):
        _tolerance_line(
            ax,
            money(config.downswing_amount_eur),
            f"downswing {config.currency.fmt(config.downswing_amount_eur)}",
            COL_DOWNSWING_LIMIT,
            legend=f"Downswing bar "
                   f"({config.currency.fmt(config.downswing_amount_eur)})",
            annotate=annotate,
        )
    if config.risk_mode in ("ruin", "both"):
        # Free, unlike the mirror image on the ruin chart: risk of ruin is
        # analytic, so every plotted point can be judged exactly with no
        # simulation and the crossing is found on the real verdicts.
        cut = _cut_point(
            [allocation for _, allocation in points],
            lambda a: a.risk_of_ruin <= config.ruin_tolerance,
            lambda a: money(measured[a.counts]),
        )
        if cut is not None:
            _tolerance_line(
                ax, cut,
                f"ruin {_odds(config.ruin_tolerance)}",
                COL_RUIN_LIMIT, y=0.10,
                legend=f"Ruin bar bites here ({_odds(config.ruin_tolerance)})",
                annotate=annotate,
            )

    if best is not None and best.counts in measured:
        _mark_best(ax, measured[best.counts], best, config, annotate=annotate)
    if current is not None and current.counts in measured:
        _mark_current(ax, measured[current.counts], current, config, annotate=annotate)

    ax.xaxis.set_major_formatter(FuncFormatter(_thousands))
    ax.set_xlabel(_tolerance.axis_label("downswing", config))
    ax.set_ylabel(config.currency.axis("/ hour"))
    ax.grid(alpha=0.9)
    ax.set_axisbelow(True)
    if annotate:
        ax.set_title("The same choice, priced in downswings rather than ruin")
        _subtitle(ax, downswing_subtitle(config))
    if legend:
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncols=4)


def downswing_subtitle(config: Config) -> str:
    """What the downswing axis measures. Public for the same reason as
    `ruin_subtitle`: the deck prints it rather than drawing it."""
    from . import sim

    return (
        f"How deep a fall from a high each mix runs, {config.downswing_probability:.0%} "
        f"of the time, over {config.downswing_hands:,} hands "
        f"({sim.TOLERANCE_PATHS:,} simulated lifetimes each)."
    )


PAIR_FIGSIZE = (14.4, 5.0)
"""Canvas for the two-panel slide - two 7.2 x 5in panels.

Sized to the HOLE IN THE SLIDE, not to the panels: the deck gives this picture
12.48 x 4.36in once the title and the notes strip are taken out, an aspect of
about 2.87, and a canvas cut to that shape fills it exactly. Any squarer canvas
scales to the height and then leaves the sides empty, which is the usual way a
side-by-side ends up looking like an accident. Change one and check the other -
the two numbers are a pair (`deck._frontier_pair_slide`)."""


def _pair_legend(fig, config: Config) -> None:
    """ONE key for both panels, drawn from proxy artists.

    The panels' own legends cannot be used here. Each is centred under its own
    axes at three or four columns, which is already at the limit of a full-width
    chart and overflows a half-width one - the right-hand key ran off the canvas
    and the left-hand one collided with it. They also say the same thing twice:
    the same six marks appear on both panels, under two sets of wording that
    differ only in phrasing ('Efficient frontier' / 'Efficient over these').

    So the pair gets a curated key instead. Both bars are drawn the same way on
    the panels too, so the entries here match them exactly.
    """
    from matplotlib.lines import Line2D

    def mark(colour, size):
        return dict(
            marker="o", linestyle="none", color=colour, markersize=size,
            markeredgecolor=MARK_EDGE, markeredgewidth=1.0,
        )

    entries = [
        Line2D([], [], marker="o", linestyle="none", color=INK_MUTED, alpha=0.5,
               markersize=4, label="Every mix scored"),
        Line2D([], [], color=COL_FRONTIER, linewidth=2.0, marker="o", markersize=4.5,
               markeredgewidth=0, label="Efficient frontier"),
        Line2D([], [], **mark(STATUS_GOOD, 9), label="Best inside tolerance"),
        Line2D([], [], **mark(COL_CURRENT_MARK, 9), label="What you are playing now"),
    ]
    if config.risk_mode in ("ruin", "both"):
        entries.append(Line2D(
            [], [], color=COL_RUIN_LIMIT, linewidth=1.6, linestyle="--",
            label=f"Ruin bar ({_odds(config.ruin_tolerance)})",
        ))
    if config.risk_mode in ("downswing", "both"):
        entries.append(Line2D(
            [], [], color=COL_DOWNSWING_LIMIT, linewidth=1.6, linestyle="--",
            label=f"Downswing bar ({config.currency.fmt(config.downswing_amount_eur)})",
        ))
    fig.legend(
        handles=entries, loc="lower center", ncols=len(entries),
        frameon=False, fontsize=9,
    )


def frontier_pair_figure(config: Config, figsize=PAIR_FIGSIZE, annotate: bool = False):
    """Both frontier charts on one canvas, ruin left and downswing right.

    The same decision priced two ways, which is a comparison the reader can only
    make properly when both are in the eye at once - across a slide boundary they
    have to remember the first picture to read the second.

    Unannotated by DEFAULT, unlike the single-chart figures: half-width panels
    have nowhere to put a three-line callout that is not on top of the data, so
    this one exists to be paired with slide text (`frontier_notes`).
    """
    _style()
    fig, (left, right) = plt.subplots(1, 2, figsize=figsize)
    _draw_allocation_frontier(left, config, annotate=annotate, legend=False)
    _draw_downswing_frontier(right, config, annotate=annotate, legend=False)
    # Panel headings even in the unannotated version: with two pictures side by
    # side, "which one am I looking at" cannot be answered by the slide title.
    # The reading instructions still live in the slide text.
    left.set_title("Priced in risk of ruin")
    right.set_title("Priced in downswings")
    # Room reserved for the shared key BEFORE it is drawn: a figure legend is not
    # part of the layout, so tight_layout would otherwise fill the space and the
    # key would land on the axis labels.
    fig.tight_layout(rect=(0, 0.09, 1, 1))
    _pair_legend(fig, config)
    return fig


def frontier_notes(
    config: Config, best=None, current=None, which: str = "both",
    compact: bool = False,
):
    """The text that used to be written onto the frontier charts.

    Returns `(heading, colour, [lines])` blocks for the deck to typeset beside
    the picture. Built here rather than in `deck.py` so the wording and the
    colours stay tied to the marks they describe - a legend that drifts from its
    chart is worse than no legend.

    `best`/`current` are optional only so a caller that has not computed them can
    still get the limit and reading blocks; passing the same objects the chart was
    drawn from is the point.

    `which` selects which chart(s) the reading instructions describe - 'ruin',
    'downswing', or 'both' for the two-panel slide.

    `compact` folds each mix onto two lines, for the two-panel slide where the
    notes sit in a strip under the picture rather than in a full-height column.
    """
    money = config.currency
    blocks: list[tuple[str, str, list[str]]] = []

    def mix_lines(allocation) -> list[str]:
        money_line = (
            f"{_hourly(allocation.eur_per_hour, config)}  |  "
            f"{money.fmt(allocation.exposure_eur)} on tables"
        )
        ruin_line = f"risk of ruin {_odds(allocation.risk_of_ruin)}"
        if compact:
            return [allocation.label, f"{money_line}  |  {ruin_line}"]
        return [allocation.label, money_line, ruin_line]

    if best is not None:
        blocks.append(
            ("Best inside tolerance (green circle)", STATUS_GOOD, mix_lines(best))
        )
    if current is not None:
        lines = mix_lines(current)
        if best is not None:
            gap = config.currency.from_eur(best.eur_per_hour - current.eur_per_hour)
            lines.append(f"{gap:+,.0f} {money.code}/hr left on the table")
        blocks.append(("What you are playing now (blue circle)", COL_CURRENT_MARK, lines))

    limits = []
    if config.risk_mode in ("ruin", "both"):
        limits.append(
            f"Ruin bar: {_odds(config.ruin_tolerance)} - the RED line. On the ruin "
            "chart it is the tolerance itself; on the downswing chart it is where "
            "that tolerance starts rejecting mixes."
        )
    if config.risk_mode in ("downswing", "both"):
        limits.append(
            f"Downswing bar: {money.fmt(config.downswing_amount_eur)} over "
            f"{config.downswing_hands:,} hands at {config.downswing_probability:.0%} "
            "- the ORANGE line, read the same way round."
        )
    if limits:
        blocks.append(("The limits", COL_RUIN_LIMIT, limits))

    reading = []
    if which in ("ruin", "both"):
        reading.append(ruin_subtitle(config))
    if which in ("downswing", "both"):
        reading.append(downswing_subtitle(config))
    blocks.append(("How to read it", INK_SECONDARY, reading))
    return blocks


def allocation_frontier_downswing(config: Config, path: Path) -> Path:
    """Render the downswing frontier chart to `path`."""
    fig = allocation_frontier_downswing_figure(config)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


RANDOM_PATHS = 20
"""Lifetimes drawn on the spaghetti chart. Enough to show the spread, few
enough that a single line can still be followed across the page."""

_RANDOM_PATH_SEED = 20260813
"""Fixed, so the same twenty lifetimes appear every rebuild. A chart that
reshuffles on every run invites the reader to rerun until they like it."""


COL_RAKEBACK = "#1baf7a"

CEILING_HEADROOM = 1.12
"""How far above the tallest honest bar each panel's axis reaches.

Both panels of the win-rate chart scale off the stakes whose modelled rate IS the
measurement, and off nothing else. The alternative - a fixed ceiling, which this
used to be on the money panel - cannot work: it is a number in one currency at
one table count, so on any other config it is either far above every bar (leaving
the panel four-fifths empty) or below them. Scaling off the data keeps the bars
legible and lets the thin stakes' enormous intervals clip, which is what the
arrows are for."""


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

    def ceiling_for(in_euros):
        """Scale a panel off the stakes whose rate IS the measurement.

        The assumed stakes have intervals of +/-50 bb/100 and worse. Letting
        those set the height flattens every honest bar into the bottom inch to
        show a whisker whose only message is 'we know nothing here' - which the
        arrow already says.

        Both panels use the same rule, on their own units. The money panel used
        to take a fixed 300 EUR instead, which on this config sat four times
        above the tallest bar and left the whole thing squashed along the floor.
        """
        highs = []
        for screen in screens:
            stake = screen.stake
            back = rates.rakeback_bb100(stake.rake_bb100, config.rakeback_pct)
            scale = (
                config.currency.from_eur(stake.bb_eur * hours_per_100)
                if in_euros else 1.0
            )
            highs.append(stake.winrate_bb100 * scale + back * scale)
            if stake.hands and stake.measured_winrate_bb100 is None:
                highs.append(
                    (stake.winrate_bb100 + back) * scale
                    + estimation.Z_95 * scale * estimation.winrate_stderr(
                        stake.stdev_bb100, stake.hands)
                )
        return max(highs) * CEILING_HEADROOM

    for ax, in_euros in ((left, False), (right, True)):
        ceiling = ceiling_for(in_euros)
        tops = []
        for index, screen in enumerate(screens):
            stake = screen.stake
            rakeback = rates.rakeback_bb100(stake.rake_bb100, config.rakeback_pct)
            # One conversion factor per panel: bb/100 -> money per hour across the
            # whole table count, or 1.0 to stay in big blinds. The currency step is
            # folded into the same factor, so the panel is drawn in display units
            # and every label on it can be formatted plainly.
            scale = (
                config.currency.from_eur(stake.bb_eur * hours_per_100)
                if in_euros
                else 1.0
            )
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
            ax.set_ylabel(config.currency.axis(f"/ hour across {config.tables} tables"))
            ax.set_title("What that edge is worth")
            _subtitle(right, "Same edges, priced in money. Arrow: interval runs "
                             "off the axis.")
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

    Returns (profit_ylim, drawdown_xmax), both in EUROS. Without this each chart
    autoscales to its own data, and two mixes drawn at different scales look far
    more alike than they are - the whole point of putting them on consecutive
    slides is that the reader can compare heights directly. Computed across every
    result that will be plotted, so the widest one sets the frame and nothing
    clips.

    In PROFIT space, not bankroll: zero is where you started, and the ruin
    barrier sits at minus the bankroll. That keeps the y-axis about the thing the
    simulation is actually telling you - how much you made or lost - rather than
    burying it in an offset every reader has to subtract in their head.

    `allocations` are the mixes whose EV lines get drawn; their endpoints have
    to fit too, and the EV of a mix NOT being simulated on a given slide can sit
    above everything on it.
    """
    import numpy as np

    top = 0.0
    hands = 0
    for result in results:
        hands = max(hands, result.hands)
        # The 95th percentile band is what the fan chart draws; the sampled rows
        # are what the spaghetti chart draws. Both have to fit.
        profit = result.checkpoint_bankroll - config.bankroll_eur
        top = max(top, float(np.percentile(profit, 95, axis=0).max()))
        top = max(top, float(profit[_random_rows(result)].max()))
    for allocation in allocations:
        top = max(top, allocation.mean_eur_per_100 * hands / 100.0)

    # The floor has to clear the ruin barrier at -bankroll, with room beneath for
    # the label that hangs under it. Headroom above for the direct labels.
    return (-1.18 * config.bankroll_eur, 1.08 * top), max(
        (float(np.percentile(r.max_drawdown, 99.5)) for r in results), default=None
    )


def simulation_figure(result, config: Config, ylim=None, drawdown_xmax=None,
                      style_key: str = "optimal", annotate: bool = True):
    """Two panels: where the bankroll goes, and how deep it digs on the way.

    Left is a fan of percentile bands rather than a spaghetti of paths - with
    twenty thousand lifetimes, individual lines are noise. A handful are drawn
    over the top anyway, because a band alone hides how jagged a single real
    year looks.

    Right is the distribution of the worst peak-to-trough fall per lifetime,
    which is the number with no closed form and therefore the reason this
    simulation exists at all.

    `style_key` picks the mix palette (`MIX_STYLES`), so the optimum is green and
    the mix in play is blue on every chart in the deck. `annotate=False` strips
    the titles and the direct labels and adds a shared key instead - the deck
    prints the numbers beside the picture.
    """
    import numpy as np

    _style()
    fig, (left, right) = plt.subplots(1, 2, figsize=(11.5, 5.2),
                                      gridspec_kw={"width_ratios": [1.35, 1]})

    # Every money quantity below is converted ONCE, here, on the way to the
    # canvas. The simulation itself never leaves euros.
    #
    # And plotted as PROFIT, not bankroll: zero is where you started, so the line
    # reads as what you made rather than as a total carrying a constant offset.
    # Ruin then has a place on the axis - the barrier at minus the bankroll -
    # instead of being the invisible point where the total happens to reach nil.
    money = config.currency.from_eur
    line_colour, mass = MIX_STYLES[style_key]
    ruin_level = money(-config.bankroll_eur)
    paths = money(result.checkpoint_bankroll - config.bankroll_eur)
    drawdowns = money(result.max_drawdown)

    hands = result.checkpoint_hands
    for low, high, alpha in ((5, 95, 0.10), (25, 75, 0.16)):
        lo = np.percentile(paths, low, axis=0)
        hi = np.percentile(paths, high, axis=0)
        left.fill_between(hands, lo, hi, color=mass, alpha=alpha, linewidth=0)
        for edge in (lo, hi):
            left.plot(hands, edge, color=line_colour, linewidth=0.9,
                      linestyle="--", alpha=0.85)
    median = np.percentile(paths, 50, axis=0)
    left.plot(hands, median, color=line_colour, linewidth=2.2, label="Median")

    # Sample paths chosen by where they FINISH - the lifetimes that ended at the
    # 5th, 20th, 40th, 60th, 80th and 95th percentile. Drawing a random handful
    # instead would over-represent the middle and never show you a bad year,
    # which is the one you want to look at.
    finals = result.final_bankroll
    order = np.argsort(finals)
    picks = [order[min(int(p / 100 * len(order)), len(order) - 1)]
             for p in (5, 20, 40, 60, 80, 95)]
    for row in picks:
        left.plot(hands, paths[row], color=COL_PATHS, linewidth=0.7, alpha=0.75)

    # Break-even, and the barrier. They are a whole bankroll apart now, so both
    # labels can sit at the left without colliding.
    left.axhline(0, color=INK_MUTED, linewidth=1.2)
    left.axhline(ruin_level, color=STATUS_CRITICAL, linewidth=1.4, linestyle="--")
    if annotate:
        left.annotate("break even", xy=(1.0, 0), xycoords=("axes fraction", "data"),
                      xytext=(-4, 6), textcoords="offset points", ha="right",
                      fontsize=9, color=INK_MUTED)
        left.annotate(
            f"ruin - lose the {config.currency.fmt(config.bankroll_eur)} roll "
            f"({result.ruin_probability:.2%} of lifetimes)",
            xy=(0, ruin_level), xytext=(4, 6), textcoords="offset points",
            fontsize=9, color=STATUS_CRITICAL, fontweight="bold",
        )
    left.set_xlabel("Hands played")
    left.set_xlim(0, hands[-1])
    left.set_ylabel(f"Net income ({config.currency.code})")
    left.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v / 1000:.0f}k"))
    # Six-figure bankrolls make "150,000" labels that crowd the axis; k-abbreviated
    # they stay readable and match the drawdown panel beside them.
    left.yaxis.set_major_formatter(FuncFormatter(_thousands))
    left.grid(axis="y", alpha=0.9)
    left.set_axisbelow(True)
    if ylim is not None:
        left.set_ylim(money(ylim[0]), money(ylim[1]))
    left.set_title("What you end up making")
    if annotate:
        # Kept SHORT deliberately: the two subtitles sit side by side at the top
        # of their panels, and a long one on the left runs straight across the
        # divider into the right panel's text. Neither should exceed about sixty
        # characters.
        _subtitle(left, "5-95 and 25-75 percentile bands, over six sampled lifetimes.")

    # Clip the tail: a handful of extreme lifetimes otherwise stretch the axis to
    # four times the interesting range and squash the whole distribution left.
    x_max = (
        money(drawdown_xmax) if drawdown_xmax is not None
        else float(np.percentile(drawdowns, 99.5))
    )
    right.hist(drawdowns, bins=60, range=(0, x_max),
               color=mass, alpha=0.95, linewidth=0)
    for pct, style, height in ((50, "-", 0.97), (90, ":", 0.86)):
        value = float(np.percentile(drawdowns, pct))
        right.axvline(value, color=INK, linewidth=1.4, linestyle=style)
        if annotate:
            right.annotate(f"{pct}th: {config.currency.code} {value:,.0f}",
                           xy=(value, height),
                           xycoords=("data", "axes fraction"), xytext=(6, 0),
                           textcoords="offset points", fontsize=9, color=INK,
                           fontweight="bold", va="top")
    # Only when the roll is actually on this axis. On a bankroll comfortably
    # bigger than any drawdown the line falls outside the x limits, and matplotlib
    # keeps drawing the LABEL - which then floats in empty space to the right of
    # the histogram attached to nothing. Off-scale is itself the good news, so it
    # is stated in words instead.
    # A DEPTH on this axis, so it stays positive even though the fan chart beside
    # it now draws the same quantity as a negative profit.
    roll_depth = money(config.bankroll_eur)
    if roll_depth <= x_max:
        right.axvline(roll_depth, color=STATUS_CRITICAL, linewidth=1.4, linestyle="--")
        if annotate:
            right.annotate("your whole roll", xy=(roll_depth, 0.50),
                           xycoords=("data", "axes fraction"), xytext=(-6, 0),
                           textcoords="offset points", ha="right", fontsize=9,
                           color=STATUS_CRITICAL, fontweight="bold")
    elif annotate:
        # Top LEFT: the distribution starts well right of zero (a mix that never
        # dug at all is not a thing), so the left shoulder of this panel is the
        # one reliably empty corner. The right is where the tail and the
        # percentile labels live.
        right.annotate(
            f"your whole roll\n({config.currency.fmt(config.bankroll_eur)}) is off\n"
            f"this axis to the right",
            xy=(0.03, 0.95), xycoords="axes fraction", ha="left", va="top",
            fontsize=9, color=STATUS_CRITICAL, fontweight="bold",
        )
    right.set_xlim(0, x_max)
    # Four ticks, k-abbreviated: six labels of the form "10,000" collide in a
    # panel this narrow, which is what produced the smear along the bottom.
    right.xaxis.set_major_locator(MaxNLocator(nbins=4))
    right.xaxis.set_major_formatter(FuncFormatter(_thousands))
    right.set_xlabel(f"Worst peak-to-trough fall ({config.currency.code})")
    right.set_ylabel("Lifetimes")
    right.set_ylim(bottom=0)
    right.grid(axis="y", alpha=0.9)
    right.set_axisbelow(True)
    right.set_title("How deep it digs")
    if annotate:
        _subtitle(right, "One value per lifetime: its worst drawdown.")
        fig.tight_layout()
    else:
        fig.tight_layout(rect=(0, 0.09, 1, 1))
        _fan_legend(fig, config, line_colour, mass, roll_depth <= x_max)
    return fig


def _fan_legend(fig, config: Config, line_colour, mass, roll_on_axis: bool) -> None:
    """One key for both panels of the bare fan chart.

    The panels show different things, so the entries run left panel first and then
    right - which is also the order the eye reads them in. The 50th/90th drawdown
    rules are black on both panels because they are read off the axis rather than
    identified by colour."""
    from matplotlib.lines import Line2D

    entries = [
        Line2D([], [], color=line_colour, linewidth=0.9, linestyle="--",
               label="Middle 50% of lifetimes"),
        Line2D([], [], color=line_colour, linewidth=0.9, linestyle="--", alpha=0.55,
               label="5th-95th percentile"),
        Line2D([], [], color=line_colour, linewidth=2.2, label="Median lifetime"),
        Line2D([], [], color=COL_PATHS, linewidth=0.7, label="Six sampled lifetimes"),
        Line2D([], [], color=INK_MUTED, linewidth=1.2, label="Break even"),
        Line2D([], [], color=STATUS_CRITICAL, linewidth=1.4, linestyle="--",
               label=("Ruin barrier / your whole roll" if roll_on_axis
                      else f"Ruin - lose the {config.currency.fmt(config.bankroll_eur)} roll")),
        Line2D([], [], color=INK, linewidth=1.4, label="Median worst fall"),
        Line2D([], [], color=INK, linewidth=1.4, linestyle=":",
               label="90th-percentile worst fall"),
    ]
    fig.legend(handles=entries, loc="lower center", ncols=4, frameon=False,
               fontsize=9)


MIX_STYLES = {
    "optimal": (STATUS_GOOD, TINT_GREEN),
    "current": (COL_CURRENT_MARK, TINT_BLUE),
}
"""(line colour, mass colour) per mix, shared by every simulation chart.

The same green means "the optimum" and the same blue means "what you play now" on
every slide in the deck, including the frontier charts' two circles. A reader who
has learnt the pair once does not have to re-learn it per picture."""


def lifetimes_figure(
    panels, config: Config, paths_drawn: int = 20, ev_lines=(), ylim=None,
    bands: bool = True, annotate: bool = True, figsize=None,
):
    """Individual simulated lifetimes, one panel per mix.

    `panels` is a sequence of (heading, result, style_key) - one entry for a
    single-mix slide, two for the current-versus-optimal comparison. Two panels
    share one y-axis by construction (`ylim` comes from `simulation_scales`),
    because the entire point of putting them side by side is that the heights can
    be compared directly.

    Three layers, deliberately in this order:

    * the percentile BANDS (5-95 and 25-75), the shape of the distribution;
    * `paths_drawn` single LIFETIMES, sampled at random - NOT picked by where they
      finish - so the spread is the one the simulation produced. They are what a
      band cannot show: nobody experiences a percentile, and a real year is jagged;
    * the EV lines, dotted, one per mix in `ev_lines`. Straight, because
      expectation is linear in hands: the curve people expect is compounding, and
      nothing here compounds - the mix is static and the stakes never move.

    Both EV lines are drawn on BOTH panels, so the comparison reads the same way
    round whichever panel the eye starts on.

    No median line: for a sum of many independent hands the median and the mean
    sit on top of each other, so it would be a second line tracing the dotted one
    and adding nothing but ink.
    """
    import numpy as np

    _style()
    if figsize is None:
        figsize = (11.5, 5.2) if len(panels) == 1 else PAIR_FIGSIZE
    fig, axes = plt.subplots(
        1, len(panels), figsize=figsize, sharey=True, squeeze=False,
    )

    money = config.currency.from_eur
    ruin_level = money(-config.bankroll_eur)

    for ax, (heading, result, style_key) in zip(axes[0], panels):
        line_colour, mass = MIX_STYLES[style_key]
        paths = money(result.checkpoint_bankroll - config.bankroll_eur)
        hands = result.checkpoint_hands

        # The interval EDGES are the thing being read, so they are drawn as
        # lines - thin, dashed, in the mix colour - with the fill left as a wash
        # behind them. A fill alone has no boundary to point at, and under a
        # screenful of lifetimes its edge is exactly where it gets lost.
        if bands:
            for low, high, alpha in ((5, 95, 0.10), (25, 75, 0.16)):
                lo = np.percentile(paths, low, axis=0)
                hi = np.percentile(paths, high, axis=0)
                ax.fill_between(hands, lo, hi, color=mass, alpha=alpha, linewidth=0)
                for edge in (lo, hi):
                    ax.plot(hands, edge, color=line_colour, linewidth=0.9,
                            linestyle="--", alpha=0.85)

        # Grey, and thinner than anything else on the chart: twenty lifetimes are
        # TEXTURE - what the spread feels like one year at a time - not twenty
        # series to be told apart. In the mix colour they competed with the
        # interval edges and the EV line, which are the two things being read.
        rng = np.random.default_rng(_RANDOM_PATH_SEED)
        count = min(paths_drawn, paths.shape[0])
        for row in rng.choice(paths.shape[0], size=count, replace=False):
            ax.plot(hands, paths[row], color=COL_PATHS, linewidth=0.7, alpha=0.75)

        # Break-even and the barrier, drawn the same way on every panel - same
        # weight and dash as the frontier charts' limit lines, for the same
        # reason: one kind of stroke means "a line someone drew", and colour says
        # which one.
        ax.axhline(0, color=INK_MUTED, linewidth=1.2)
        ax.axhline(ruin_level, color=STATUS_CRITICAL, linewidth=1.4, linestyle="--")

        # Last, so they sit on top of the spaghetti rather than under it.
        for label, allocation, colour in ev_lines:
            line = money(allocation.mean_eur_per_100 * (hands / 100.0))
            ax.plot(hands, line, color=colour, linewidth=2.2, linestyle="--")
            if annotate:
                ax.annotate(
                    f"{label} EV  {config.currency.code} {line[-1]:,.0f}",
                    xy=(hands[-1], line[-1]), xytext=(-4, 8),
                    textcoords="offset points", ha="right", fontsize=9,
                    fontweight="bold", color=colour,
                )

        if annotate:
            ax.annotate("break even", xy=(1.0, 0), xycoords=("axes fraction", "data"),
                        xytext=(-4, 6), textcoords="offset points", ha="right",
                        fontsize=9, color=INK_MUTED)
            ax.annotate(
                f"ruin - lose the {config.currency.fmt(config.bankroll_eur)} roll "
                f"({result.ruin_probability:.2%} of lifetimes)",
                xy=(0, ruin_level), xytext=(4, 6), textcoords="offset points",
                fontsize=9, color=STATUS_CRITICAL, fontweight="bold",
            )

        ax.set_xlabel("Hands played")
        # Hand zero is the left edge - see the note on zero-based axes.
        ax.set_xlim(0, hands[-1])
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v / 1000:.0f}k"))
        ax.grid(axis="y", alpha=0.9)
        ax.set_axisbelow(True)
        if ylim is not None:
            ax.set_ylim(money(ylim[0]), money(ylim[1]))
        # A heading per panel even when nothing else is written on the chart: with
        # two of them, "which mix is this" cannot be answered by the slide title.
        # On a single panel the title does answer it, so the caller passes "".
        if heading:
            ax.set_title(heading)

    axes[0][0].set_ylabel(f"Net income ({config.currency.code})")
    axes[0][0].yaxis.set_major_formatter(FuncFormatter(_thousands))

    if annotate:
        fig.tight_layout()
    else:
        # Two rows of key, so more bottom margin than the frontier pair's one row.
        fig.tight_layout(rect=(0, 0.14, 1, 1))
        _lifetimes_legend(fig, config, ev_lines, bands=bands)
    return fig


def _lifetimes_legend(fig, config: Config, ev_lines, bands: bool = True) -> None:
    """One key under the panels - see `_pair_legend` for why it is not per-axes.

    The band and lifetime entries are drawn in the OPTIMAL palette, because those
    elements take their colour from whichever panel they are in; the panel
    headings and the EV entries carry the mix identity. One pair of band entries
    per panel would say the same thing twice.
    """
    from matplotlib.lines import Line2D

    entries = [
        Line2D([], [], color=COL_PATHS, linewidth=0.7,
               label="Single lifetimes, drawn at random"),
    ]
    if bands:
        entries += [
            Line2D([], [], color=STATUS_GOOD, linewidth=0.9, linestyle="--",
                   label="Middle 50% of lifetimes"),
            Line2D([], [], color=STATUS_GOOD, linewidth=0.9, linestyle="--",
                   alpha=0.55, label="5th-95th percentile"),
        ]
    entries += [
        Line2D([], [], color=colour, linewidth=2.2, linestyle="--",
               label=f"{label} EV (variance off)")
        for label, _, colour in ev_lines
    ]
    entries += [
        Line2D([], [], color=INK_MUTED, linewidth=1.2, label="Break even"),
        Line2D([], [], color=STATUS_CRITICAL, linewidth=1.4, linestyle="--",
               label=f"Ruin - lose the {config.currency.fmt(config.bankroll_eur)} roll"),
    ]
    # FOUR columns, not one row of seven. Seven entries this wordy overflow the
    # canvas and matplotlib clips the last one silently - the ruin entry lost its
    # closing word before this was capped. Two rows of four also matches the fan
    # chart's key, so the two simulation slides look like siblings.
    fig.legend(handles=entries, loc="lower center", ncols=4, frameon=False,
               fontsize=9)


def simulation_notes(config: Config, panels, ev_lines=(), compact: bool = False):
    """The wording that used to be written onto the simulation charts.

    Same contract as `frontier_notes`: `(heading, colour, [lines])` blocks for the
    deck to typeset beside or beneath the picture, each heading in the colour of
    the thing it describes.

    `panels` is the same sequence `lifetimes_figure` takes, so a slide cannot
    describe a mix it did not draw.
    """
    import numpy as np

    money = config.currency
    blocks: list[tuple[str, str, list[str]]] = []

    for heading, result, style_key in panels:
        line_colour, _ = MIX_STYLES[style_key]
        finals = result.final_bankroll - config.bankroll_eur
        low, high = (float(np.percentile(finals, p)) for p in (5, 95))
        median_dd = float(np.percentile(result.max_drawdown, 50))
        if compact:
            lines = [
                result.allocation.label,
                f"90% finish {money.fmt(low)} to {money.fmt(high)}  |  "
                f"typical worst fall {money.fmt(median_dd)}  |  "
                f"ruin {result.ruin_probability:.2%}",
            ]
        else:
            lines = [
                result.allocation.label,
                f"90% of lifetimes finish between {money.fmt(low)} and "
                f"{money.fmt(high)}",
                f"typical worst drawdown {money.fmt(median_dd)}",
                f"{result.ruin_probability:.2%} of lifetimes lose the roll",
            ]
        blocks.append((heading or result.allocation.label, line_colour, lines))

    if ev_lines:
        hands = panels[0][1].hands
        blocks.append(("The dotted lines", INK, [
            "  ".join(
                f"{label} EV finishes at "
                f"{money.fmt(allocation.mean_eur_per_100 * hands / 100)}."
                for label, allocation, _ in ev_lines
            ),
            "Straight because expectation is linear in hands - nothing here "
            "compounds, since the mix is static and the stakes never move.",
        ]))

    blocks.append(("How to read it", INK, [
        f"{panels[0][1].hands:,} hands per lifetime "
        f"({panels[0][1].hours:,.0f} hours at {config.tables} tables), "
        f"{panels[0][1].paths:,} lifetimes simulated.",
        "The mix is held fixed with no move-down rule, so every risk figure here "
        "is an upper bound rather than a forecast.",
    ]))
    return blocks


def write_all(config: Config, directory: Path) -> list[Path]:
    """Render both frontier charts into `directory`.

    Two charts, deliberately - the same trade-off measured the two ways risk can
    be stated, so the one that did not bind is still there to be checked against.
    Earlier versions also drew per-stake ruin curves, a Kelly-fraction trade-off
    and a win-rate funnel; none of them answered the question being asked, and
    each one was another thing to read past.

    The downswing chart costs a simulation per point, so it is the slow one.
    """
    _style()
    directory.mkdir(parents=True, exist_ok=True)
    try:
        return [
            allocation_frontier(config, directory / "frontier.png"),
            allocation_frontier_downswing(config, directory / "frontier_downswing.png"),
        ]
    except mix.AllocationLimit:
        return []
