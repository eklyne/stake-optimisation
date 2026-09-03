"""`sims.pptx` - the same simulation, one lifetime per slide.

The main deck draws twenty lifetimes on ONE picture, which answers "what is the
spread". It cannot answer "what does one of these actually look like, and what
would the year have felt like" - twenty grey lines on top of each other have no
individual numbers attached, and the deepest fall on any one of them is a shape
you can see but not read.

So this is the same model, sliced the other way: `TRIALS` single lifetimes per
mix, one per slide, every slide on IDENTICAL axes so the deck can be flicked
through and compared by eye, each with its own numbers overlaid in the corner.

Unlike anything else in the repo, these slides SPLIT THE MONEY: the lifetime is
drawn as what the cards paid, plus rakeback, plus the total of the two. Rakeback
carries no variance (`rates.rakeback_bb100`), so it is a dead straight ramp and
the two curves are the same shape a fixed distance apart - which is the point.
Every downswing here is measured on the TABLE line, because that is the fall that
actually happened; the bankroll's fall over the same stretch is shallower by
whatever rakeback arrived while it was going on, and both numbers are quoted. A
fall reported only net of rakeback understates what has to be sat through, and
one reported only gross overstates what it costs.

Three things are deliberately different from `sim.simulate`:

* the paths are kept at FULL 100-hand resolution rather than the 120 checkpoints
  the fan chart stores, because the drawdown numbers on the table are measured
  off the path itself - a checkpointed path would understate every fall it
  dipped into and out of between samples;
* consequently only `TRIALS` of them are drawn, not twenty thousand;
* they are their OWN draw. They are not the twenty rows the main deck's
  spaghetti chart samples (those exist only at checkpoint resolution), so a
  figure here will not match a line there. Both are samples from the same
  distribution; neither is more real than the other.

Everything else is the model the rest of the repo uses - a static mix, fixed
sizing, no move-down rule, ruin absorbing - so the figures reconcile with the
main deck's percentiles.

Money is EUROS internally and converted only at the point of labelling, exactly
as in `charts` and `deck` (see `money.py`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402
from pptx.util import Inches, Pt  # noqa: E402

from . import charts, pptx_common as pc  # noqa: E402
from .config import Config  # noqa: E402
from .mix import Allocation  # noqa: E402
from .sim import _HANDS_PER_STEP, _resolve_seed  # noqa: E402

__all__ = ["TRIALS", "Trial", "run_trials", "trial_figure", "write"]

TRIALS = 20
"""Lifetimes per mix, and therefore slides per mix.

Twenty is the count the main deck already draws on its spaghetti chart, so the
two sections describe the same sized sample; it is also about as many as anyone
will flick through in one sitting."""

_SEEDS = {"optimal": 20260823, "current": 20260824}
"""One fixed seed per mix, so a rebuild reproduces the same twenty lifetimes and
a comment pinned to 'trial 7' still describes trial 7. DIFFERENT per mix on
purpose: a shared seed would make trial 7 of one mix the same coin flips as
trial 7 of the other, which invites reading a pair of slides as one controlled
comparison. They are independent draws and the deck says so."""


@dataclass
class Trial:
    """One simulated lifetime, kept whole."""

    index: int
    """1-based, as it is titled on the slide."""
    style_key: str
    """`charts.MIX_STYLES` key - which mix this is a lifetime of."""
    allocation: Allocation
    hands: np.ndarray = field(repr=False)
    """Hand count at each step, starting at 0."""
    equity_eur: np.ndarray = field(repr=False)
    """Profit against the STARTING bankroll at each step, euros. Starts at 0.

    The TOTAL - what the bankroll actually did, cards and rakeback together. It
    is the series the ruin barrier is checked against, because a rebate spends
    the same as a pot."""
    rakeback_eur: np.ndarray = field(repr=False)
    """The rakeback part of `equity_eur` at each step, euros. Starts at 0.

    Deterministic given the hands played - a straight ramp at
    `allocation.rakeback_eur_per_100` per step - so it is not drawn from the
    generator, it is computed. It stops when the lifetime does: a ruined path
    plays no more hands, so it earns no more rebate."""
    stats: dict = field(default_factory=dict, repr=False)

    @property
    def table_eur(self) -> np.ndarray:
        """What the cards paid: the total less the rakeback in it.

        Derived rather than stored, so the three lines on the slide cannot
        disagree by construction - the split is exact at every step."""
        return self.equity_eur - self.rakeback_eur


def _buyin_eur(allocation: Allocation) -> float:
    """The average buy-in across the tables being played, in euros.

    A mix spans stakes, so "buy-ins won" has no single answer. The tables are
    all dealt at the same rate, so the table-weighted average buy-in is the
    honest converter - it is what a hand from this mix is worth on average.
    Every slide quoting buy-ins states the figure used, because the same money
    is a different number of buy-ins once a 400NL table is in the mix.
    """
    tables = sum(allocation.counts)
    return allocation.exposure_eur / tables if tables else 0.0


def _describe(config: Config, allocation: Allocation, equity: np.ndarray,
              rakeback: np.ndarray, hands: np.ndarray, ruined: bool) -> dict:
    """Everything the corner table quotes, measured off the path itself.

    `equity` is the TOTAL and `rakeback` the part of it that was rebate, so the
    cards paid the difference. What is measured off which matters:

    * the money rows are all three - what you banked, and the two things it was
      made of;
    * the DOWNSWING is measured on the table line. That is the fall as it was
      played: rakeback arrives on a schedule that knows nothing about how the
      cards are running, so subtracting it first invents a smoother year than
      the one that happened. What it did do is quoted beside it - the rebate
      earned over exactly that stretch, and therefore the shallower fall the
      bankroll took, which is the total line's own drop across the same span;
    * `worst_below_start`, `below_even` and the end bankroll are on the TOTAL,
      because those are questions about money you have rather than about how the
      cards ran.
    """
    buyin = _buyin_eur(allocation)
    table = equity - rakeback
    total_hands = int(hands[-1])
    won = float(equity[-1])
    won_rakeback = float(rakeback[-1])
    won_table = float(table[-1])

    def per_100(amount: float) -> float:
        """Realised bb/100 for a component, off the same buy-in conversion the
        money rows use - so a component rate and its money cannot disagree."""
        if not buyin or not total_hands:
            return 0.0
        return (amount / (buyin / 100.0)) / (total_hands / 100.0)

    # Peak-to-trough, the same definition the main simulation uses: the running
    # high-water mark includes the start, so a lifetime that never gets above
    # water still has its fall measured from zero rather than from its own best
    # losing moment.
    peak = np.maximum.accumulate(table)
    fall = peak - table
    trough_at = int(np.argmax(fall))
    depth = float(fall[trough_at])
    # The FIRST step that reached the high the fall started from - so the
    # duration is the length of the fall, not of the plateau in front of it.
    peak_at = int(np.argmax(table[: trough_at + 1]))

    # Rakeback banked while the fall was happening. The net figure is then
    # identically the TOTAL line's drop over the same span, since the split is
    # exact at every step - it is not a second, differently-measured drawdown.
    rakeback_over = float(rakeback[trough_at] - rakeback[peak_at])
    net_depth = depth - rakeback_over

    # The deepest fall in the BANKROLL, on its own timing - which is a different
    # episode from the one above, not the same fall netted off. It is here for
    # one reason: it is the statistic the main deck's downswing tolerance is
    # written in (`sim._max_drawdown_samples` runs on total equity), so without
    # it a reader flicking through these slides would compare a table fall with
    # a bankroll limit and think the rule had been broken.
    roll_fall = float((np.maximum.accumulate(equity) - equity).max())

    recovered = np.nonzero(table[trough_at:] >= table[peak_at])[0]
    recovery_hands = int(recovered[0]) * _HANDS_PER_STEP if len(recovered) else None
    # And the same question of the bankroll, which gets there sooner because the
    # rebate keeps arriving: back to the money you had when the fall started.
    recovered_net = np.nonzero(equity[trough_at:] >= equity[peak_at])[0]
    recovery_net_hands = (
        int(recovered_net[0]) * _HANDS_PER_STEP if len(recovered_net) else None
    )

    return {
        "buyin_eur": buyin,
        "hands": total_hands,
        "won_eur": won,
        "won_table_eur": won_table,
        "won_rakeback_eur": won_rakeback,
        "won_buyins": won / buyin if buyin else 0.0,
        "won_table_buyins": won_table / buyin if buyin else 0.0,
        "won_rakeback_buyins": won_rakeback / buyin if buyin else 0.0,
        # Realised bb/100 over the lifetime, off the same buy-in conversion as
        # the line above, so the two cannot disagree.
        "bb100": per_100(won),
        "bb100_table": per_100(won_table),
        "bb100_rakeback": per_100(won_rakeback),
        "drawdown_eur": depth,
        "drawdown_buyins": depth / buyin if buyin else 0.0,
        "drawdown_rakeback_eur": rakeback_over,
        "drawdown_rakeback_buyins": rakeback_over / buyin if buyin else 0.0,
        "drawdown_net_eur": net_depth,
        "drawdown_net_buyins": net_depth / buyin if buyin else 0.0,
        "roll_drawdown_eur": roll_fall,
        "roll_drawdown_buyins": roll_fall / buyin if buyin else 0.0,
        "drawdown_hands": (trough_at - peak_at) * _HANDS_PER_STEP,
        "drawdown_from": peak_at * _HANDS_PER_STEP,
        "drawdown_to": trough_at * _HANDS_PER_STEP,
        "drawdown_peak_table_eur": float(table[peak_at]),
        "drawdown_trough_table_eur": float(table[trough_at]),
        "recovery_hands": recovery_hands,
        "recovery_net_hands": recovery_net_hands,
        "worst_below_start_eur": float(max(0.0, -equity.min())),
        "below_even_pct": float((equity < 0).mean()),
        "end_bankroll_eur": max(0.0, config.bankroll_eur + won),
        "ruined": ruined,
    }


def run_trials(config: Config, allocation: Allocation, style_key: str,
               count: int = TRIALS, hands: int | None = None,
               seed: int | None = None) -> list[Trial]:
    """`count` whole lifetimes of this mix, kept at 100-hand resolution.

    Same generator as `sim.simulate` - one normal draw per 100-hand block, which
    is exact for the diffusion the model is - and ruin is absorbing here too: a
    path that reaches zero stops there rather than trading its way back.

    Honours `sim.FRESH_SEEDS` through `_resolve_seed`, so `--fresh-sims` redraws
    these slides along with everything else.
    """
    hands = config.timescale_hands if hands is None else hands
    steps = hands // _HANDS_PER_STEP
    if steps < 1:
        raise ValueError(f"hands must be at least {_HANDS_PER_STEP}, got {hands}")

    seed = _SEEDS[style_key] if seed is None else seed
    rng = np.random.default_rng(_resolve_seed(seed))

    mean = allocation.mean_eur_per_100
    stdev = float(np.sqrt(allocation.variance_eur_per_100))
    draws = rng.normal(mean, stdev, size=(count, steps))
    walks = np.concatenate([np.zeros((count, 1)), np.cumsum(draws, axis=1)], axis=1)

    hand_axis = np.arange(steps + 1) * _HANDS_PER_STEP
    # The rakeback inside those totals - the same rebate on every lifetime,
    # since it is paid on hands dealt and nothing else. Taken off the mean
    # rather than out of the generator ON PURPOSE: putting it through the normal
    # draw would give a rebate a variance it does not have.
    ramp = hand_axis / 100.0 * allocation.rakeback_eur_per_100

    trials = []
    for index in range(count):
        equity = walks[index]
        rakeback = ramp
        busted = np.nonzero(equity <= -config.bankroll_eur)[0]
        ruined = bool(len(busted))
        if ruined:
            equity = equity.copy()
            equity[busted[0]:] = -config.bankroll_eur
            # A busted lifetime deals no more hands, so it earns no more
            # rakeback either. Freezing the ramp with the path keeps the split
            # exact past the barrier - otherwise the table line would carry on
            # falling underneath a flat total, which never happened.
            rakeback = ramp.copy()
            rakeback[busted[0]:] = rakeback[busted[0]]
        trials.append(Trial(
            index=index + 1,
            style_key=style_key,
            allocation=allocation,
            hands=hand_axis,
            equity_eur=equity,
            rakeback_eur=rakeback,
            stats=_describe(config, allocation, equity, rakeback, hand_axis, ruined),
        ))
    return trials


def trial_scales(config: Config, trials, ev_lines=()) -> tuple[float, float]:
    """ONE y-range for every slide in the deck, in euros.

    The whole point of the section is flicking between slides, and an axis that
    autoscaled per lifetime would make a good year and a bad one the same
    height. Computed across every path that will be drawn plus both EV lines, so
    nothing clips; the floor clears the ruin barrier with room for its label.

    "Every path" includes the TABLE line, which runs below the total by whatever
    rakeback has been earned so far and therefore sets the floor on most slides.
    """
    top = max(float(trial.equity_eur.max()) for trial in trials)
    bottom = min(float(trial.table_eur.min()) for trial in trials)
    horizon = max(int(trial.hands[-1]) for trial in trials)
    for _, allocation, _ in ev_lines:
        top = max(top, allocation.mean_eur_per_100 * horizon / 100.0)
    pad = 0.06 * (top - bottom) if top > bottom else abs(top) or 1.0
    return (min(bottom - pad, -1.12 * config.bankroll_eur), top + pad)


def trial_figure(trial: Trial, config: Config, ylim=None, ev_lines=(),
                 figsize=(12.2, 5.6)):
    """One lifetime, on the deck's shared frame.

    THREE lines, not one: what the cards paid, the rakeback on the same volume,
    and the total of the two. The total is the subject of the slide and is drawn
    as such; the two components are thin, because they are what it is made of
    rather than two more things to follow. Rakeback is straight - it is a rebate
    on hands dealt, not a gamble - so the picture also makes the reason the two
    curves separate visible: it is time, not luck.

    The one thing drawn here that is on no chart in the main deck: the deepest
    peak-to-trough fall is SHADED, from the high it started at to the low it
    reached, with its depth written beside it. It is measured and drawn on the
    TABLE line, which is where a downswing actually happens; the annotation then
    says what rakeback gave back over that stretch, which is the (shallower)
    distance the total line fell between the same two hand counts. Those are
    three of the rows in the corner table, and a number in a table you cannot
    point at on the picture is a number nobody checks.
    """
    charts._style()
    fig, ax = plt.subplots(figsize=figsize)

    money = config.currency.from_eur
    line_colour, mass = charts.MIX_STYLES[trial.style_key]
    hands = trial.hands
    equity = money(trial.equity_eur)
    stats = trial.stats
    # With no rakeback the three lines are one line, and drawing a flat zero
    # ramp under the total would be three keys for one fact.
    split = trial.rakeback_eur[-1] > 0

    # The worst fall, behind everything else: a wash between the two hand counts
    # it spans, and a dropped line at the trough showing how far it went.
    if stats["drawdown_eur"] > 0:
        ax.axvspan(stats["drawdown_from"], stats["drawdown_to"],
                   color=charts.COL_DOWNSWING_LIMIT, alpha=0.13, linewidth=0)
        high = money(stats["drawdown_peak_table_eur"])
        low = money(stats["drawdown_trough_table_eur"])
        ax.plot([stats["drawdown_to"]] * 2, [high, low],
                color=charts.COL_DOWNSWING_LIMIT, linewidth=1.6,
                marker="_", markersize=9)

    ax.axhline(0, color=charts.INK_MUTED, linewidth=1.2)
    ax.axhline(money(-config.bankroll_eur), color=charts.STATUS_CRITICAL,
               linewidth=1.4, linestyle="--")

    for _, allocation, colour in ev_lines:
        ax.plot(hands, money(allocation.mean_eur_per_100 * (hands / 100.0)),
                color=colour, linewidth=2.0, linestyle="--", alpha=0.9)

    # The two halves, under the total and thinner than it. Rakeback keeps the
    # green it is given on the win-rate chart, so a reader who has met it there
    # meets the same colour here.
    if split:
        ax.plot(hands, money(trial.table_eur), color=COL_TABLE_WINNINGS,
                linewidth=1.0, alpha=0.95)
        ax.plot(hands, money(trial.rakeback_eur), color=charts.COL_RAKEBACK,
                linewidth=1.0)

    # The lifetime itself, on top and in the mix colour - here it IS the subject
    # of the slide, not texture behind a band, so it does not get the spaghetti
    # chart's grey.
    ax.plot(hands, equity, color=line_colour, linewidth=1.7)
    ax.fill_between(hands, 0, equity, color=mass, alpha=0.18, linewidth=0)

    ax.set_xlabel("Hands played")
    ax.set_ylabel(f"Net income ({config.currency.code})")
    ax.set_xlim(0, hands[-1])
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v / 1000:.0f}k"))
    ax.yaxis.set_major_formatter(FuncFormatter(charts._thousands))
    ax.grid(axis="y", alpha=0.9)
    ax.set_axisbelow(True)
    if ylim is not None:
        ax.set_ylim(money(ylim[0]), money(ylim[1]))

    # Last, because where it goes depends on the axis being settled: see
    # `_annotate_fall`.
    if stats["drawdown_eur"] > 0:
        _annotate_fall(ax, config, stats, split, money)

    fig.tight_layout(rect=(0, 0.13, 1, 1))
    _legend(fig, config, ev_lines, line_colour, split)
    return fig


def _annotate_fall(ax, config: Config, stats: dict, split: bool, money) -> None:
    """Name the shaded fall, beside the trough it belongs to.

    ONE line, and in the colour of the line it is measured on rather than the
    colour of the shading - a label the width of the picture is not a label, and
    the reader can follow grey text to the grey path without being told. What
    rakeback gave back over the fall is two rows of the corner table; it does
    not need saying twice.

    It hangs BELOW the trough, on whichever side of it there is room. That is
    also why the numbers block sits at the top of the picture rather than in the
    bottom-right corner it used to: a bad lifetime troughs low, and the label
    naming the trough wants exactly the space a table down there would take.

    It is also KEPT OUT OF THE LAYOUT, which is the whole reason this is a
    function worth having. The label is about half the width of the axes and it
    is not clipped, so wherever it overhangs the frame it lands in the axes'
    tight bounding box - and `tight_layout` then shrinks the plot to make room
    for it, by a different amount on every slide. A section built to be flicked
    through cannot have the frame breathing in and out under the paths, so the
    label is excluded from the layout calculation and allowed to overhang.
    `_LABEL_WIDTH` is which way it hangs: to the right of an early trough and to
    the left of a late one, chosen so that the overhang goes into the tick-label
    gutter rather than off the right-hand edge, where it would be cropped.
    """
    low = money(stats["drawdown_trough_table_eur"])
    left, right = ax.get_xlim()
    early = (stats["drawdown_to"] - left) / (right - left) < 1.0 - _LABEL_WIDTH

    label = (
        f"Worst downswing: {config.currency.fmt(stats['drawdown_eur'])},"
        f" {stats['drawdown_buyins']:,.1f} buy-ins,"
        f" {stats['drawdown_hands']:,} hands"
        + (" (excl. rakeback)" if split else "")
    )
    annotation = ax.annotate(
        label,
        xy=(stats["drawdown_to"], low),
        xytext=(6 if early else -6, -15),
        textcoords="offset points", fontsize=9, fontweight="bold",
        color=COL_TABLE_WINNINGS, ha="left" if early else "right",
        va="top",
        # On a shared axis the label lands wherever the trough is, which is
        # sometimes on top of the path. A panel behind it keeps it legible
        # without moving it away from the fall it names.
        bbox=dict(facecolor=charts.SURFACE, edgecolor="none", alpha=0.85,
                  boxstyle="square,pad=0.25"),
    )
    # The one line that keeps every slide in the section the same size.
    annotation.set_in_layout(False)


_LABEL_WIDTH = 0.55
"""How much of the axes width the fall label takes, near enough.

Only used to decide which side of the trough it hangs off, and deliberately
rounded UP from the measured half: erring high hangs a middling trough's label
to the left, into the gutter, instead of off the right edge where the end of it
would be cut."""


COL_TABLE_WINNINGS = charts.INK_SECONDARY
"""The table-winnings line. A GREY, not a third colour with an opinion.

The two components have to be told apart at a glance, and the deck already
spends green on rakeback (`charts.COL_RAKEBACK`) and the two mix colours on
which mix a slide belongs to. Grey keeps the total the thing the eye lands on
while leaving the line it is drawn from legible underneath it - and the fall
being shaded is marked in orange, which is what points at this line anyway."""


def _legend(fig, config: Config, ev_lines, line_colour, split: bool = False) -> None:
    """One key per slide, in the same place on every slide - see the deck's own
    `_lifetimes_legend` for why it hangs off the figure and not the axes.

    TWO ROWS, unlike the main deck's: splitting the lifetime added two entries
    and the single row was already running the full width of the picture. It
    fills column by column, which is how matplotlib lays a legend out, so the
    pairs sitting above each other belong together - the lifetime and its parts,
    then the two EV lines, then the two reference levels.
    """
    from math import ceil

    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    entries = [
        # In the colour it is actually drawn in - which is the mix identity, and
        # the one element of the key that changes between the two sections.
        Line2D([], [], color=line_colour, linewidth=1.7,
               label="This lifetime, banked" if split else "This lifetime"),
        *([Line2D([], [], color=COL_TABLE_WINNINGS, linewidth=1.0,
                  label="Won at the tables"),
           Line2D([], [], color=charts.COL_RAKEBACK, linewidth=1.0,
                  label="Rakeback (no variance)")] if split else []),
        Patch(facecolor=charts.COL_DOWNSWING_LIMIT, alpha=0.25,
              label="Deepest fall at the tables" if split
              else "Deepest peak-to-trough fall"),
        *(Line2D([], [], color=colour, linewidth=2.0, linestyle="--",
                 label=f"{label} EV (variance off)")
          for label, _, colour in ev_lines),
        Line2D([], [], color=charts.INK_MUTED, linewidth=1.2, label="Break even"),
        Line2D([], [], color=charts.STATUS_CRITICAL, linewidth=1.4, linestyle="--",
               label=f"Ruin - lose the {config.currency.fmt(config.bankroll_eur)} roll"),
    ]
    fig.legend(handles=entries, loc="lower center", ncols=ceil(len(entries) / 2),
               frameon=False, fontsize=9)


# --------------------------------------------------------------------------- #
# Slides
# --------------------------------------------------------------------------- #
def _money(config: Config, eur: float, dp: int = 0) -> str:
    """A euro amount in the display currency, with its code - as `deck._money`."""
    return config.currency.fmt(eur, dp)


def _money_buyins(config: Config, eur: float, buyins: float,
                  sign: bool = False, unit: bool = True) -> str:
    """A money figure with its buy-in count in brackets, in one cell.

    One row instead of two, which is what buys the space the split needed - and
    the two are never read apart anyway. `unit` writes the `bi` out, for the
    corner table, which is an overlay with no room for a units line and where a
    bare number in brackets could be anything. The summary has a header to say
    it and gets the shorter form, which is what keeps twelve columns on the
    slide."""
    count = f"{buyins:+,.1f}" if sign else f"{buyins:,.1f}"
    return f"{_money(config, eur)} ({count}{' bi' if unit else ''})"


def _recovered(config: Config, stats: dict) -> str:
    """How long the fall took to get back, at the tables and in the bankroll.

    The bankroll gets there first whenever there is rakeback, because the rebate
    keeps arriving through the fall - so the two are quoted together, and
    collapse to one figure when they agree (or when there is no rakeback)."""
    at_tables = stats["recovery_hands"]
    net = stats["recovery_net_hands"]
    text = f"{at_tables:,}" if at_tables is not None else "never"
    if net == at_tables:
        return text
    return f"{text} (roll {net:,})" if net is not None else f"{text} (roll never)"


_TABLE_ROWS = [
    [
        ("Hands", lambda c, s: f"{s['hands']:,}"),
        ("Won",
         lambda c, s: _money_buyins(c, s["won_eur"], s["won_buyins"], sign=True)),
        ("- at the tables",
         lambda c, s: _money_buyins(c, s["won_table_eur"], s["won_table_buyins"],
                                    sign=True)),
        ("- rakeback",
         lambda c, s: _money_buyins(c, s["won_rakeback_eur"],
                                    s["won_rakeback_buyins"], sign=True)),
        ("Win rate", lambda c, s: f"{s['bb100']:+.2f} bb/100"),
        ("Below even", lambda c, s: f"{s['below_even_pct']:.0%} of hands"),
        ("End bankroll", lambda c, s: _money(c, s["end_bankroll_eur"])),
    ],
    [
        ("Fall at the tables",
         lambda c, s: _money_buyins(c, s["drawdown_eur"], s["drawdown_buyins"])),
        ("- rakeback over it",
         lambda c, s: _money_buyins(c, s["drawdown_rakeback_eur"],
                                    s["drawdown_rakeback_buyins"])),
        ("- so the roll fell",
         lambda c, s: _money_buyins(c, s["drawdown_net_eur"],
                                    s["drawdown_net_buyins"])),
        ("It took, hands", lambda c, s: f"{s['drawdown_hands']:,}"),
        ("Recovered in, hands", _recovered),
        ("Worst fall in the roll",
         lambda c, s: _money_buyins(c, s["roll_drawdown_eur"],
                                    s["roll_drawdown_buyins"])),
        ("Worst vs start", lambda c, s: _money(c, s["worst_below_start_eur"])),
    ],
]
"""The corner table, as TWO blocks side by side: what you made on the left, what
it cost to sit through on the right. Every row is measured off THIS path - none
of them is a percentile.

Two blocks rather than one column of fourteen because of where it has to sit.
The old single column was already as tall as the winning half of the axis, and
splitting the money into three rows would have pushed its top through the end of
the path it describes. Wide and short, it lives in the band under the break-even
line, which is empty on any lifetime that is winning - and on one that is not,
so is the top-right corner the column used to keep clear.

The indented rows are PARTS of the row above them and sum to it exactly. "Fall
at the tables" is the deepest peak-to-trough fall in what the cards paid, which
the slide also shades and names in full; the rakeback beneath it is what arrived
over that same stretch, so the third row is how far the bankroll itself fell
between those two hand counts. "Worst fall in the roll" is a DIFFERENT episode -
the bankroll's own deepest fall, wherever it happened - and it is the one on the
main deck's downswing rule, which is why it is quoted even though this slide
does not shade it.

Labels are terse because the table is an OVERLAY - every extra millimetre of it
is a millimetre of chart nobody can see."""

_TABLE_WIDTHS = (0.90, 1.55, 1.15, 1.30)
"""Inches per column: label, value, label, value.

Sized off the longest string each one can hold - `Worst fall in the roll` and
`GBP 61,925 (+344.8 bi)`, the value columns generously, since these cells do not
wrap: text that outgrows one is painted over by the fill of the cell beside it
and simply disappears.

And no wider than that. At 4.90in the block covers the left 44% of the axes,
which is the most it can take and still clear every one of the forty lifetimes
the section draws - the hottest of them reaches 75.6k at 470k hands, under a
block whose floor sits at 83k. Widen it and that slide loses its own peak behind
the numbers describing it."""


def _stats_table(slide, config: Config, trial: Trial, picture, box) -> None:
    """The numbers, overlaid on the TOP-LEFT of the chart.

    Overlaid rather than beside: the chart is the slide, and a side column would
    take the width the horizon needs. Top-left because that is the corner the
    picture cannot use: every lifetime starts at zero and the axis is shared
    across the section, so its ceiling is set by the best of twenty at the end
    of a million hands - nothing is ever drawn above the early hands. The
    bottom-right corner it used to sit in only looks empty. It is where a losing
    lifetime goes, and where the label naming the deepest fall hangs.

    It is kept as SMALL as it can be read at, and pushed as far into the corner
    as the axes allow, because every millimetre of it is a millimetre of the
    lifetime it is describing that the reader cannot see. That is the whole
    trade: fourteen numbers against the picture they came from.

    `box` is the axes rectangle read off the laid-out figure, in figure
    coordinates from the BOTTOM-left, rather than guessed - so a change to the
    legend, the tick labels or the axis titles moves the table with them.
    """
    columns = _TABLE_ROWS
    rows = max(len(column) for column in columns) + 1
    width = Inches(sum(_TABLE_WIDTHS))
    row_height = Inches(0.175)
    height = Inches(0.175 * rows)
    # Sat ON the plotting area, inside the frame rather than over the furniture:
    # the y tick labels are to the LEFT of `box.x0` and the title is above the
    # picture, so a table pinned just inside that corner covers neither.
    left = int(picture.left + box.x0 * picture.width + Inches(0.06))
    top = int(picture.top + (1.0 - box.y1) * picture.height + Inches(0.06))

    shape = slide.shapes.add_table(rows, 2 * len(columns), left, top, width, height)
    table = shape.table
    for index, column_width in enumerate(_TABLE_WIDTHS):
        table.columns[index].width = Inches(column_width)
    for row in table.rows:
        row.height = row_height

    # A busted lifetime says so in its own header, in red: every row below it
    # still reads as a normal year otherwise, since the bankroll is pinned at
    # the barrier rather than going negative. The heading runs in the first cell
    # and the rest of the header row is filled but empty, so the black strip
    # reads as one bar across both blocks.
    heading = f"Trial {trial.index} of {TRIALS}"
    if trial.stats["ruined"]:
        heading += " - RUINED"
    for index in range(2 * len(columns)):
        cell = table.cell(0, index)
        pc._zero_cell_margins(cell)
        pc.set_cell(cell, heading if index == 0 else "", font_size=8, bold=True,
                    bg_colour=pc.TABLE_HEADER_BG,
                    font_colour=pc.COL_RED if trial.stats["ruined"] else pc.WHITE)

    for block, entries in enumerate(columns):
        for row, (label, render) in enumerate(entries, start=1):
            for index, text in enumerate((label, render(config, trial.stats))):
                cell = table.cell(row, 2 * block + index)
                pc._zero_cell_margins(cell)
                # Solid fills, because this sits ON the chart: a transparent cell
                # would have grid lines and a path running through the digits.
                pc.set_cell(cell, text, font_size=8, bold=(index == 1),
                            bg_colour=pc.TABLE_LABEL_BG if index == 0 else pc.WHITE,
                            font_colour=pc.BLACK)
        # A block with fewer rows than the tallest still needs its cells filled,
        # or they render transparent and the chart shows through the table.
        for row in range(len(entries) + 1, rows):
            for index in range(2):
                cell = table.cell(row, 2 * block + index)
                pc._zero_cell_margins(cell)
                pc.set_cell(cell, "", font_size=8,
                            bg_colour=pc.TABLE_LABEL_BG if index == 0 else pc.WHITE,
                            font_colour=pc.BLACK)


def _trial_slide(prs, layouts, config: Config, trial: Trial, heading: str,
                 ylim, ev_lines) -> None:
    slide = prs.slides.add_slide(layouts["Title and Content"])
    pc.add_title(slide, f"{heading} - trial {trial.index} of {TRIALS}")

    fig = trial_figure(trial, config, ylim=ylim, ev_lines=ev_lines)
    picture = slide.shapes.add_picture(
        pc.fig_to_stream(fig, dpi=200), pc.CONTENT_LEFT, pc.CONTENT_TOP,
        height=int(pc.CONTENT_HEIGHT),
    )
    if picture.width > pc.CONTENT_WIDTH:
        aspect = picture.height / picture.width
        picture.width = int(pc.CONTENT_WIDTH)
        picture.height = int(pc.CONTENT_WIDTH * aspect)
        picture.top = int(pc.CONTENT_TOP + (pc.CONTENT_HEIGHT - picture.height) / 2)
    picture.left = int(pc.CONTENT_LEFT + (pc.CONTENT_WIDTH - picture.width) / 2)

    # Measured off the figure that was just rendered - see `_stats_table`.
    _stats_table(slide, config, trial, picture, fig.axes[0].get_position())
    plt.close(fig)


def _fall(key_eur: str, key_buyins: str):
    """A summary column that prices one fall in money and in buy-ins at once."""
    return lambda c, s: _money_buyins(c, s[key_eur], s[key_buyins], unit=False)


_SUMMARY_COLS = [
    ("Trial", 0.50, lambda c, s: f"{s['trial']}"),
    ("Hands", 0.95, lambda c, s: f"{s['hands']:,}"),
    ("Won\n(buy-ins)", 1.35,
     lambda c, s: _money_buyins(c, s["won_eur"], s["won_buyins"], sign=True,
                                unit=False)),
    ("Realised\nbb/100", 0.80, lambda c, s: f"{s['bb100']:+.2f}"),
    ("Fall at the\ntables (bi)", 1.30, _fall("drawdown_eur", "drawdown_buyins")),
    ("Rakeback\nover it", 1.05, lambda c, s: _money(c, s["drawdown_rakeback_eur"])),
    ("So the roll\nfell (bi)", 1.30,
     _fall("drawdown_net_eur", "drawdown_net_buyins")),
    ("Worst fall in\nthe roll (bi)", 1.30,
     _fall("roll_drawdown_eur", "roll_drawdown_buyins")),
    ("It took,\nhands", 1.00, lambda c, s: f"{s['drawdown_hands']:,}"),
    ("Tables\nrecovered", 1.00,
     lambda c, s: f"{s['recovery_hands']:,}" if s["recovery_hands"] is not None
     else "never"),
    ("Worst below\nstart", 1.05, lambda c, s: _money(c, s["worst_below_start_eur"])),
    ("Below\neven", 0.75, lambda c, s: f"{s['below_even_pct']:.0%}"),
]
"""The twenty at a glance. FOUR columns for the falls, deliberately.

Three of them are one event priced twice over: what the cards took away, what
rakeback handed back while they were doing it, and therefore what the bankroll
actually lost. Reading only one of those three is what this section exists to
stop. The fourth is a different event - the bankroll's own deepest fall,
wherever in the lifetime it happened - and it is there because that is the
statistic the main deck's downswing tolerance is set in, so it is the column to
read against the limit rather than the one beside it."""


def _summary_slide(prs, layouts, config: Config, trials, heading: str) -> None:
    """All twenty trials as one table - the section, before you flick through it.

    The point is the SPREAD: twenty lifetimes of one static mix read down a
    column is the argument the individual slides then illustrate one at a time.
    """
    slide = prs.slides.add_slide(layouts["Title and Content"])
    pc.add_title(slide, f"{heading} - {TRIALS} trials at a glance")

    width = Inches(sum(w for _, w, _ in _SUMMARY_COLS))
    shape = slide.shapes.add_table(
        len(trials) + 2, len(_SUMMARY_COLS),
        int(pc.CONTENT_LEFT + (pc.CONTENT_WIDTH - width) / 2),
        pc.CONTENT_TOP + Inches(0.10), width, Inches(0.40 + 0.21 * len(trials)),
    )
    table = shape.table
    for index, (_, column_width, _fmt) in enumerate(_SUMMARY_COLS):
        table.columns[index].width = Inches(column_width)

    for index, (label, _width, _fmt) in enumerate(_SUMMARY_COLS):
        cell = table.cell(0, index)
        pc._zero_cell_margins(cell)
        pc.set_cell(cell, label, font_size=9, bold=True, wrap=True,
                    bg_colour=pc.TABLE_HEADER_BG, font_colour=pc.WHITE)

    rows = []
    for trial in trials:
        row = dict(trial.stats)
        row["trial"] = trial.index
        rows.append(row)

    for row_index, row in enumerate(rows, start=1):
        for index, (_label, _width, render) in enumerate(_SUMMARY_COLS):
            cell = table.cell(row_index, index)
            pc._zero_cell_margins(cell)
            pc.set_cell(cell, render(config, row), font_size=9,
                        bold=(index == 0), font_colour=pc.BLACK)

    # The median across the twenty, as the last row. A mean would be dragged
    # around by the one lifetime that ran hot; the median is what a reader is
    # trying to eyeball off the column anyway.
    median = {
        key: float(np.median([row[key] for row in rows]))
        for key in ("hands", "won_eur", "won_buyins", "bb100", "drawdown_eur",
                    "drawdown_buyins", "drawdown_rakeback_eur",
                    "drawdown_net_eur", "drawdown_net_buyins",
                    "roll_drawdown_eur", "roll_drawdown_buyins",
                    "drawdown_hands", "below_even_pct", "worst_below_start_eur")
    }
    median["trial"] = "median"
    median["hands"] = int(median["hands"])
    median["drawdown_hands"] = int(median["drawdown_hands"])
    # A column that can read "never" has no median - the count that never got
    # back is the honest summary, and it goes in the footnote.
    never = sum(1 for row in rows if row["recovery_hands"] is None)
    recovered = [r["recovery_hands"] for r in rows if r["recovery_hands"] is not None]
    median["recovery_hands"] = int(np.median(recovered)) if recovered else None

    for index, (_label, _width, render) in enumerate(_SUMMARY_COLS):
        cell = table.cell(len(rows) + 1, index)
        pc._zero_cell_margins(cell)
        pc.set_cell(cell, render(config, median), font_size=9, bold=True,
                    bg_colour=pc.TABLE_LABEL_BG, font_colour=pc.BLACK)

    buyin = trials[0].stats["buyin_eur"]
    _footnote(
        slide,
        f"{TRIALS} independent lifetimes of {config.timescale_hands:,} hands on this "
        f"one static mix, drawn at {_HANDS_PER_STEP}-hand resolution. The fall is "
        f"measured on what the CARDS paid, since that is the downswing as it was "
        f"played. Rakeback arrives on a schedule the cards know nothing about, so it "
        f"is shown beside the fall rather than netted off it first - the third "
        f"column is what the bankroll itself lost between the same two hand counts, "
        f"and the fourth is the bankroll's own worst fall, which is usually a "
        f"different stretch of the year. "
        f"'Median' is the median of the {TRIALS}, column by column - it is not one "
        f"lifetime, and no single trial has all of those numbers together. "
        + (f"{never} of the {TRIALS} never recovered their deepest fall inside the "
           f"horizon. " if never else "")
        + f"Buy-ins convert at {config.currency.fmt(buyin)}, the table-weighted "
          f"average buy-in of this mix ({trials[0].allocation.label}) - the two "
          f"sections therefore convert at DIFFERENT buy-ins, so compare the two "
          f"mixes on money and leave buy-ins to be read within a section."
    )


def _footnote(slide, text) -> None:
    """As `deck._footnote` - copied rather than imported, because `deck` imports
    this module to build the second deck and the reverse would be circular."""
    box = slide.shapes.add_textbox(
        pc.CONTENT_LEFT, pc.CONTENT_TOP + pc.CONTENT_HEIGHT - Inches(0.85),
        pc.CONTENT_WIDTH, Inches(0.8),
    )
    frame = box.text_frame
    frame.word_wrap = True
    run = frame.paragraphs[0].add_run()
    run.text = text
    run.font.size = Pt(9)
    run.font.italic = True
    run.font.color.rgb = pc.GRID_GREY


def write(path: Path, config: Config, best, current, ev_lines=()) -> Path:
    """Build `sims.pptx` and return the path written.

    Called from `deck.build`, with the mixes it has already chosen - so the two
    decks cannot end up describing different allocations, which is the one way a
    second deck could quietly contradict the first.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    wanted = [
        (best, "optimal", "The optimal mix",
         "Twenty single lifetimes of the mix the optimiser picked"),
        (current, "current", "The mix you play now",
         "Twenty single lifetimes of the mix actually played"),
    ]
    runs = [
        (heading, subtitle, run_trials(config, allocation, style_key))
        for allocation, style_key, heading, subtitle in wanted
        if allocation is not None
    ]
    every = [trial for _, _, trials in runs for trial in trials]
    if not every:
        raise ValueError("no mixes to simulate")
    ylim = trial_scales(config, every, ev_lines)

    prs, layouts = pc.load_template_presentation()
    for index, (heading, subtitle, trials) in enumerate(runs, start=1):
        pc.add_chapter_slide(prs, layouts, f"{index}. {heading}", subtitle)
        _summary_slide(prs, layouts, config, trials, heading)
        for trial in trials:
            _trial_slide(prs, layouts, config, trial, heading, ylim, ev_lines)

    prs.save(path)
    return path
