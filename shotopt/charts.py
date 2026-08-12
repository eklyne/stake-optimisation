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

Colours are the reference data-viz values used verbatim rather than re-derived;
the charts render on the light surface only, since a PNG has no viewer theme to
respond to. Colour carries in/out of tolerance - a status, not an identity - and is
always paired with a shape and a direct label, so it never has to be read by hue
alone.

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
"""Reserved for genuine danger - the ruin barrier, and nothing else."""

COL_CURRENT = "#c2478f"
"""The mix currently played. Pink, deliberately NOT the red used for ruin: the
current mix is a reference point, not a warning, and drawing it in the danger
colour made every deck read as though it were an emergency."""

COL_RUIN_LIMIT = "#d03b3b"
COL_DOWNSWING_LIMIT = "#e08214"
"""The two risk bars, kept apart by colour as well as by dash pattern. With both
rules live there are two lines on every frontier chart, and 'which one is which'
should not require reading the small print at the axis."""

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


def _tolerance_line(
    ax, x: float, label: str, colour: str, dotted: bool = False,
    y: float = 0.02, legend: str | None = None,
) -> None:
    """A limit drawn on the axis, by a rule that was actually applied.

    Dashed for a limit that IS this axis's own quantity, so the line sits exactly
    where the number does. Dotted for the other rule's limit, which is a cut
    point rather than a threshold - see `_cut_point`.

    Colour carries WHICH RULE, dash pattern carries whether it is a threshold or
    a cut, and `legend` puts the same pairing in the key. Three redundant
    encodings for two lines is not excessive here: on a busy scatter the reader
    has to be able to tell a ruin bar from a downswing bar at a glance.

    `y` staggers the labels: with both rules in play the two lines can be close
    together, and their labels point INWARD at each other across the gap.
    """
    ax.axvline(
        x, color=colour, linewidth=1.6, linestyle=":" if dotted else "--",
        label=legend,
    )
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


def _mark_best(ax, x: float, best, config: Config) -> None:
    """The chosen mix, marked identically on both frontier charts.

    Same shape, colour and label wording on each, so the two read as one pair and
    the eye can carry the answer from one picture to the other.

    `x` arrives already in whatever units its axis is drawn in; the y value is
    converted here, because it is always money and always comes off the
    allocation in euros.
    """
    y = config.currency.from_eur(best.eur_per_hour)
    ax.plot(
        [x], [y],
        marker="o", markersize=13, color=STATUS_GOOD,
        markeredgecolor=SURFACE, markeredgewidth=2, linestyle="none",
        label="Best inside tolerance",
    )
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


def _mark_current(ax, x: float, current, config: Config) -> None:
    """The mix actually being played, so the gap to the frontier is visible rather
    than described. Vertical distance to the blue line is EV left on the table;
    horizontal distance is risk taken for nothing."""
    y = config.currency.from_eur(current.eur_per_hour)
    ax.plot(
        [x], [y],
        marker="D", markersize=11, color=COL_CURRENT,
        markeredgecolor=SURFACE, markeredgewidth=2, linestyle="none",
        label="What you are playing now",
    )
    ax.annotate(
        f"current: {_hourly(current.eur_per_hour, config)}  |  "
        f"ruin {_odds(current.risk_of_ruin)}",
        xy=(x, y),
        xytext=(10, -14), textcoords="offset points",
        color=COL_CURRENT, fontsize=9.5, fontweight="bold",
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


def _ruin_cannot_rank_figure(fig, ax, config: Config, allocations, best, current):
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
    ax.margins(y=0.34)
    ax.grid(axis="y", alpha=0.9)
    ax.set_axisbelow(True)
    ax.set_title(f"Every way to split {config.tables} tables across your stakes")
    _subtitle(
        ax,
        f"Ruin cannot rank these: all {len(allocations):,} sit under "
        f"{RUIN_NEGLIGIBLE:g}, the riskiest at {_one_in(worst)}.",
    )
    # Top LEFT: the chosen mix is the best-earning one, so it and its marker sit
    # at the right-hand end of this axis by construction, and a note over there
    # lands on top of them.
    ax.annotate(
        f"On a {config.currency.fmt(config.bankroll_eur)} bankroll ruin is not the "
        f"binding constraint,\nso this is the earnings spread instead. What separates "
        f"these mixes\nis how deep a downswing they put you through - the next chart.",
        xy=(0.02, 0.97), xycoords="axes fraction", ha="left", va="top",
        fontsize=9.5, color=INK_SECONDARY,
    )
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncols=3)
    fig.tight_layout()
    return fig


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
        return _ruin_cannot_rank_figure(fig, ax, config, allocations, best, current)

    # Follows the data rather than a constant: twelve decades below the riskiest
    # mix on this ladder. See FLOOR_DECADES.
    floor = ruin_floor(allocations)

    ax.scatter(
        [max(a.risk_of_ruin, floor) for a in allocations],
        [money(a.eur_per_hour) for a in allocations],
        s=14, color=INK_MUTED, alpha=0.28, linewidths=0, label="Every possible mix",
    )
    ax.plot(
        [max(a.risk_of_ruin, floor) for a in edge],
        [money(a.eur_per_hour) for a in edge],
        color=SERIES_BLUE, linewidth=2.0, marker="o", markersize=5,
        markeredgecolor=SURFACE, markeredgewidth=1, label="Efficient frontier",
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
        )
    if config.risk_mode in ("downswing", "both"):
        cut = _downswing_cut_on_ruin_axis(config, edge, floor)
        if cut is not None:
            _tolerance_line(
                ax, cut,
                f"downswing {config.currency.fmt(config.downswing_amount_eur)}",
                COL_DOWNSWING_LIMIT, dotted=True, y=0.10,
                legend=f"Downswing bar bites here "
                       f"({config.currency.fmt(config.downswing_amount_eur)})",
            )

    if best is not None:
        _mark_best(ax, max(best.risk_of_ruin, floor), best, config)

    if current is not None:
        _mark_current(ax, max(current.risk_of_ruin, floor), current, config)
    # Any stack remaining on the left edge is the floor, not a coincidence: those
    # mixes carry a risk too small to tell apart or to care about.
    ax.set_xlabel(
        f"Risk of ruin (log scale; under {floor:.0e} is drawn at the floor)"
    )
    ax.set_ylabel(config.currency.axis("/ hour"))
    ax.grid(alpha=0.9)
    ax.set_axisbelow(True)
    ax.set_title(f"Every way to split {config.tables} tables across your stakes")
    _subtitle(ax, {
        "ruin": "Take the highest point left of the dashed line. The frontier is the "
                "menu; everything below it is dominated.",
        "downswing": "Ruin is shown for reference - the downswing rule chose the "
                     "answer. Dotted: where that rule bites.",
        "both": "Dashed: the ruin bar. Dotted: where the downswing bar bites. The "
                "answer must clear both, so the leftmost line binds.",
    }[config.risk_mode])
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncols=3)
    fig.tight_layout()
    return fig


def allocation_frontier(config: Config, path: Path) -> Path:
    """Render the frontier chart to `path`."""
    fig = allocation_frontier_figure(config)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def allocation_frontier_downswing_figure(config: Config):
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
    """
    from . import sim, tolerance as _tolerance

    _style()
    fig, ax = plt.subplots(figsize=(9.5, 6))

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
        return fig

    points.sort(key=lambda pair: pair[0])
    # Both axes are money, so both are DRAWN in the display currency. Plotting
    # euros under a converted tick formatter would leave the axis ticking at
    # euro round numbers relabelled into ragged sterling ones.
    money = config.currency.from_eur
    measured = {allocation.counts: money(value) for value, allocation in points}

    ax.scatter(
        [money(value) for value, _ in points],
        [money(allocation.eur_per_hour) for _, allocation in points],
        s=26, color=INK_MUTED, alpha=0.45, linewidths=0, label="Frontier candidates",
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
        color=SERIES_BLUE, linewidth=2.0, marker="o", markersize=5,
        markeredgecolor=SURFACE, markeredgewidth=1, label="Efficient over these",
    )

    # Margins BEFORE anything that measures the axis. `_tolerance_line` and
    # `_mark_best` both decide which side of a point to write their label on by
    # where it falls across the axis, and an axis still autoscaling gives them a
    # different answer from the one the reader ends up seeing.
    ax.margins(x=0.10, y=0.15)
    ax.autoscale_view()

    if config.risk_mode in ("downswing", "both"):
        _tolerance_line(
            ax,
            money(config.downswing_amount_eur),
            f"downswing {config.currency.fmt(config.downswing_amount_eur)}",
            COL_DOWNSWING_LIMIT,
            legend=f"Downswing bar "
                   f"({config.currency.fmt(config.downswing_amount_eur)})",
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
                COL_RUIN_LIMIT, dotted=True, y=0.10,
                legend=f"Ruin bar bites here ({_odds(config.ruin_tolerance)})",
            )

    if best is not None and best.counts in measured:
        _mark_best(ax, measured[best.counts], best, config)
    if current is not None and current.counts in measured:
        _mark_current(ax, measured[current.counts], current, config)

    ax.xaxis.set_major_formatter(FuncFormatter(_thousands))
    ax.set_xlabel(_tolerance.axis_label("downswing", config))
    ax.set_ylabel(config.currency.axis("/ hour"))
    ax.grid(alpha=0.9)
    ax.set_axisbelow(True)
    ax.set_title("The same choice, priced in downswings rather than ruin")
    _subtitle(
        ax,
        f"How deep a fall from a high each mix runs, {config.downswing_probability:.0%} "
        f"of the time, over {config.downswing_hands:,} hands "
        f"({sim.TOLERANCE_PATHS:,} simulated lifetimes each).",
    )
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncols=4)
    fig.tight_layout()
    return fig


def allocation_frontier_downswing(config: Config, path: Path) -> Path:
    """Render the downswing frontier chart to `path`."""
    fig = allocation_frontier_downswing_figure(config)
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

    # Every money quantity below is converted ONCE, here, on the way to the
    # canvas. The simulation itself never leaves euros.
    #
    # And plotted as PROFIT, not bankroll: zero is where you started, so the line
    # reads as what you made rather than as a total carrying a constant offset.
    # Ruin then has a place on the axis - the barrier at minus the bankroll -
    # instead of being the invisible point where the total happens to reach nil.
    money = config.currency.from_eur
    ruin_level = money(-config.bankroll_eur)
    paths = money(result.checkpoint_bankroll - config.bankroll_eur)
    drawdowns = money(result.max_drawdown)

    hands = result.checkpoint_hands
    bands = [(5, 95, 0.14), (25, 75, 0.24)]
    for low, high, alpha in bands:
        left.fill_between(
            hands,
            np.percentile(paths, low, axis=0),
            np.percentile(paths, high, axis=0),
            color=SERIES_BLUE, alpha=alpha, linewidth=0,
        )
    median = np.percentile(paths, 50, axis=0)
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
        left.plot(hands, paths[row], color=INK_MUTED, linewidth=0.8, alpha=0.6)

    # Break-even, and the barrier. They are a whole bankroll apart now, so both
    # labels can sit at the left without colliding.
    left.axhline(0, color=INK_MUTED, linewidth=1.2, linestyle="--")
    left.annotate("break even", xy=(1.0, 0), xycoords=("axes fraction", "data"),
                  xytext=(-4, 6), textcoords="offset points", ha="right",
                  fontsize=9, color=INK_MUTED)
    left.axhline(ruin_level, color=STATUS_CRITICAL, linewidth=1.4, linestyle=":")
    left.annotate(
        f"ruin - lose the {config.currency.fmt(config.bankroll_eur)} roll "
        f"({result.ruin_probability:.2%} of lifetimes)",
        xy=(0, ruin_level), xytext=(4, 6), textcoords="offset points",
        fontsize=9, color=STATUS_CRITICAL, fontweight="bold",
    )
    left.set_xlabel("Hands played")
    left.set_ylabel(f"Profit from start ({config.currency.code})")
    left.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v / 1000:.0f}k"))
    # Six-figure bankrolls make "150,000" labels that crowd the axis; k-abbreviated
    # they stay readable and match the drawdown panel beside them.
    left.yaxis.set_major_formatter(FuncFormatter(_thousands))
    left.grid(axis="y", alpha=0.9)
    left.set_axisbelow(True)
    if ylim is not None:
        left.set_ylim(money(ylim[0]), money(ylim[1]))
    left.set_title("What you end up making")
    # Kept SHORT deliberately: the two subtitles sit side by side at the top of
    # their panels, and a long one on the left runs straight across the divider
    # into the right panel's text. Neither should exceed about sixty characters.
    _subtitle(left, "5-95 and 25-75 percentile bands, over six sampled lifetimes.")

    # Clip the tail: a handful of extreme lifetimes otherwise stretch the axis to
    # four times the interesting range and squash the whole distribution left.
    x_max = (
        money(drawdown_xmax) if drawdown_xmax is not None
        else float(np.percentile(drawdowns, 99.5))
    )
    right.hist(drawdowns, bins=60, range=(0, x_max),
               color=SERIES_BLUE, alpha=0.85, linewidth=0)
    for pct, style, height in ((50, "-", 0.97), (90, ":", 0.86)):
        value = float(np.percentile(drawdowns, pct))
        right.axvline(value, color=INK, linewidth=1.4, linestyle=style)
        right.annotate(f"{pct}th: {config.currency.code} {value:,.0f}", xy=(value, height),
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
        right.axvline(roll_depth, color=STATUS_CRITICAL, linewidth=1.4, linestyle=":")
        right.annotate("your whole roll", xy=(roll_depth, 0.50),
                       xycoords=("data", "axes fraction"), xytext=(-6, 0),
                       textcoords="offset points", ha="right", fontsize=9,
                       color=STATUS_CRITICAL, fontweight="bold")
    else:
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
    right.grid(axis="y", alpha=0.9)
    right.set_axisbelow(True)
    right.set_title("How deep it digs")
    _subtitle(right, "One value per lifetime: its worst drawdown.")

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

    # Profit from the starting roll, matching the fan chart beside it - see
    # `simulation_figure` for why the axis is not the bankroll itself.
    money = config.currency.from_eur
    ruin_level = money(-config.bankroll_eur)
    paths = money(result.checkpoint_bankroll - config.bankroll_eur)

    hands = result.checkpoint_hands
    rng = np.random.default_rng(_RANDOM_PATH_SEED)
    count = min(RANDOM_PATHS, paths.shape[0])
    rows = rng.choice(paths.shape[0], size=count, replace=False)
    for row in rows:
        ax.plot(hands, paths[row], color=SERIES_BLUE, linewidth=0.9, alpha=0.55)

    ax.axhline(0, color=INK_MUTED, linewidth=1.2, linestyle="--")
    ax.annotate("break even", xy=(1.0, 0), xycoords=("axes fraction", "data"),
                xytext=(-4, 6), textcoords="offset points", ha="right",
                fontsize=9, color=INK_MUTED)
    ax.axhline(ruin_level, color=STATUS_CRITICAL, linewidth=1.4, linestyle=":")
    ax.annotate(
        f"ruin - lose the {config.currency.fmt(config.bankroll_eur)} roll "
        f"({result.ruin_probability:.2%} of lifetimes)",
        xy=(0, ruin_level), xytext=(4, 6), textcoords="offset points",
        fontsize=9, color=STATUS_CRITICAL, fontweight="bold",
    )

    # Drawn last so they sit on top of the spaghetti, and labelled directly at
    # the right-hand end rather than in a legend the eye has to travel to.
    for label, allocation, colour in ev_lines:
        line = money(allocation.mean_eur_per_100 * (hands / 100.0))
        ax.plot(hands, line, color=colour, linewidth=2.0, linestyle=":")
        ax.annotate(f"{label} EV  {config.currency.code} {line[-1]:,.0f}",
                    xy=(hands[-1], line[-1]), xytext=(-4, 8),
                    textcoords="offset points", ha="right", fontsize=9,
                    fontweight="bold", color=colour)

    ax.set_xlabel("Hands played")
    ax.set_ylabel(f"Profit from start ({config.currency.code})")
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v / 1000:.0f}k"))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.grid(axis="y", alpha=0.9)
    ax.set_axisbelow(True)
    if ylim is not None:
        ax.set_ylim(money(ylim[0]), money(ylim[1]))
    ax.set_title("Where the bankroll ends up - twenty single lifetimes")
    _subtitle(
        ax,
        f"{count} lifetimes drawn at random from the {result.paths:,} simulated. "
        "Dotted: the EV of each mix, variance switched off.",
    )

    fig.tight_layout()
    return fig


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
