"""Monte Carlo over a fixed hand horizon, for one static mix.

Everything the closed forms can answer, they answer. This exists for the things
they cannot:

* **Peak-to-trough drawdown**, which has no lifetime value to quote - over
  unlimited time it grows without bound, so the only meaningful question is how
  deep it gets within a stated number of hands.
* **Where the bankroll actually ends up**, not merely whether it survived.
* **How often ruin arrives inside a horizon you will really play**, which is
  lower than the all-time figure the analytic model reports.

The model is deliberately the same one the rest of the repo uses, so the two can
be checked against each other: a static allocation, played at fixed size, with
no move-down rule. That makes it a conservative upper bound on risk rather than
a forecast - a real player would drop down long before busting.

The one analytic anchor: over a long horizon the DEEPEST-BELOW-START
distribution must converge to `ruin.loss_below_start_quantile`. `tests/test_sim`
asserts it. A simulation that disagrees with the closed form in the case the
closed form covers is a simulation with a bug.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .config import Config
from .mix import Allocation

__all__ = [
    "SimResult",
    "simulate",
    "expected_drawdown",
    "drawdown_quantile",
    "DEFAULT_HANDS",
    "DEFAULT_PATHS",
    "TABLE_PATHS",
    "TOLERANCE_PATHS",
    "SCREEN_PATHS",
]

DEFAULT_HANDS = 1_000_000
DEFAULT_PATHS = 20_000

TABLE_PATHS = 4_000
"""Lifetimes simulated per table row.

Fewer than the headline charts use: a median and a 99th percentile settle down
long before a histogram looks smooth, and this runs once per row across a dozen
mixes. Named rather than left as a default argument so the slide footnotes can
state the real figure instead of a number that might drift out of step."""

TOLERANCE_PATHS = TABLE_PATHS
"""Lifetimes behind a downswing tolerance VERDICT.

Same figure as a table row and for the same reason - a single quantile settles
long before a histogram does. Named separately because this one decides which mix
you play, so if it ever needs to move it should move on its own argument."""

SCREEN_PATHS = 500
"""Lifetimes behind the cheap first pass.

`tolerance.DownswingTolerance.admits` screens at this count and only pays for
`TOLERANCE_PATHS` on candidates that survive. Rejecting a mix whose drawdown is
half again over the limit does not need four thousand paths, and the walk down the
frontier rejects far more candidates than it accepts."""

_HANDS_PER_STEP = 100
"""Simulate in 100-hand blocks, the unit the win rate and variance arrive in.

Aggregating hands into blocks is not an approximation of the model - the model
is already a diffusion, so a block is exactly one normal draw with 100 hands'
mean and variance. It IS an approximation of reality at the margin: within-block
detail is lost, so a drawdown that dips and recovers inside 100 hands goes
unseen. At the depths that matter here that is immaterial.
"""

_CHECKPOINTS = 120
"""How many points along the path to retain for the fan chart. Storing every
step for every path is what turns this from seconds into gigabytes."""


@dataclass
class SimResult:
    """Outcome of one simulation run."""

    allocation: Allocation
    hands: int
    paths: int
    bankroll_eur: float

    ruin_probability: float
    """Share of paths whose bankroll hit zero inside the horizon."""
    max_drawdown: np.ndarray
    """Per path: deepest peak-to-trough fall, euros."""
    loss_below_start: np.ndarray
    """Per path: deepest fall below the STARTING bankroll, euros. This is the
    one ruin depends on, and the one the closed form covers."""
    final_bankroll: np.ndarray
    """Per path: bankroll at the horizon, euros. Busted paths are held at 0."""

    checkpoint_hands: np.ndarray = field(repr=False)
    checkpoint_bankroll: np.ndarray = field(repr=False)
    """(paths x checkpoints) bankroll samples along the way, for charting."""

    def percentiles(self, values: np.ndarray, points=(5, 25, 50, 75, 95)) -> dict:
        return {p: float(np.percentile(values, p)) for p in points}

    @property
    def hours(self) -> float:
        """Horizon in hours, at the configured table count and speed."""
        return self._hours

    _hours: float = 0.0


_DRAWDOWN_CACHE: dict = {}


def _max_drawdown_samples(
    config: Config, allocation: Allocation, hands: int, paths: int
) -> tuple[np.ndarray, float]:
    """The per-lifetime worst peak-to-trough falls, and the ruin rate beside them.

    Cached on everything the simulation actually consumes. Note what is IN the
    key: `mean_eur_per_100` and `variance_eur_per_100`, not the stake mix. Those
    two numbers, the bankroll and the horizon are the entire input to `simulate` -
    so two different allocations that happen to share them have the same drawdown
    distribution by construction, and the second one is free. That is not an
    approximation, and the downswing walk in `mix` leans on it heavily.

    The raw array is cached rather than a fixed set of percentiles, so any
    quantile a caller wants afterwards costs nothing. Four thousand floats per
    entry is nothing next to re-running the paths.
    """
    key = (
        config.bankroll_eur,
        hands,
        paths,
        allocation.mean_eur_per_100,
        allocation.variance_eur_per_100,
    )
    cached = _DRAWDOWN_CACHE.get(key)
    if cached is None:
        result = simulate(config, allocation, hands=hands, paths=paths, seed=4242)
        cached = (result.max_drawdown, result.ruin_probability)
        _DRAWDOWN_CACHE[key] = cached
    return cached


def drawdown_quantile(
    config: Config,
    allocation: Allocation,
    hands: int,
    quantile: float,
    paths: int = TOLERANCE_PATHS,
) -> float:
    """The peak-to-trough fall this mix reaches at `quantile`, over `hands` hands.

    Read it as: with probability `1 - quantile`, a stretch of `hands` hands
    contains a downswing at least this deep. The 0.95 quantile is the one a 5%
    downswing tolerance is testing against.

    Euros, like everything else internal.
    """
    if not 0.0 < quantile < 1.0:
        raise ValueError(f"quantile must be in (0, 1), got {quantile}")
    samples, _ = _max_drawdown_samples(config, allocation, hands, paths)
    return float(np.percentile(samples, quantile * 100.0))


def expected_drawdown(
    config: Config, allocation: Allocation, hands: int, paths: int = TABLE_PATHS
) -> dict[str, float]:
    """Peak-to-trough drawdown to expect over `hands` hands. Simulated.

    The number a player actually experiences: how far the bankroll falls from
    whatever high it had reached, within a stretch of play you can picture.
    Procedure, spelled out because the slides quote it: simulate one lifetime of
    `hands` hands; within it find the single deepest peak-to-trough fall, giving
    one number for that lifetime; repeat `paths` times; report the median and the
    99th percentile of those numbers. So "median worst downswing" is the median
    of the WORST fall per lifetime - not the median of every downswing, most of
    which are trivial.

    There is no closed form for this - peak-to-trough has no all-time
    distribution to invert, which is exactly why it needs simulating and why the
    horizon has to be stated. Deliberately cheap (a few thousand paths) because
    it is called once per table row; the headline simulation slide runs far more.

    Shares `_max_drawdown_samples`' cache with the downswing tolerance, so a mix
    the optimiser already tested costs nothing to put on a slide.
    """
    samples, ruin_probability = _max_drawdown_samples(config, allocation, hands, paths)
    return {
        "median": float(np.percentile(samples, 50)),
        "p90": float(np.percentile(samples, 90)),
        "p99": float(np.percentile(samples, 99)),
        # The literal worst of the simulated lifetimes. Reported for interest,
        # NOT used on slides: it is whatever the unluckiest of N paths happened
        # to hit, so it drifts upward as N grows and changes with the seed. The
        # 99th percentile answers the same question and holds still.
        "max": float(samples.max()),
        "ruin": ruin_probability,
    }


def simulate(
    config: Config,
    allocation: Allocation,
    hands: int = DEFAULT_HANDS,
    paths: int = DEFAULT_PATHS,
    seed: int | None = 20260808,
) -> SimResult:
    """Run `paths` independent lifetimes of `hands` hands on one allocation.

    Ruin is ABSORBING: once a path's bankroll reaches zero it stops there rather
    than being allowed to recover. Letting busted paths trade their way back
    would quietly understate ruin and flatter every percentile above it.
    """
    if hands < _HANDS_PER_STEP:
        raise ValueError(f"hands must be at least {_HANDS_PER_STEP}, got {hands}")
    if paths < 1:
        raise ValueError(f"paths must be at least 1, got {paths}")

    mean = allocation.mean_eur_per_100
    stdev = math.sqrt(allocation.variance_eur_per_100)
    bankroll = config.bankroll_eur

    steps = hands // _HANDS_PER_STEP
    rng = np.random.default_rng(seed)

    equity = np.zeros(paths)          # profit relative to the starting bankroll
    peak = np.zeros(paths)            # running high-water mark of equity
    max_dd = np.zeros(paths)
    worst_below_start = np.zeros(paths)
    ruined = np.zeros(paths, dtype=bool)

    checkpoint_steps = np.unique(
        np.linspace(1, steps, min(_CHECKPOINTS, steps)).astype(int)
    )
    checkpoints = np.zeros((paths, len(checkpoint_steps)))
    next_checkpoint = 0

    done = 0
    while done < steps:
        chunk = min(2000, steps - done)
        draws = rng.normal(mean, stdev, size=(paths, chunk))
        # A busted path stops moving. Zeroing its increments is cheaper than
        # masking, and equivalent once its equity is pinned below.
        draws[ruined] = 0.0
        walk = equity[:, None] + np.cumsum(draws, axis=1)

        running_peak = np.maximum(np.maximum.accumulate(walk, axis=1), peak[:, None])
        max_dd = np.maximum(max_dd, (running_peak - walk).max(axis=1))
        worst_below_start = np.maximum(worst_below_start, (-walk).max(axis=1))

        newly_ruined = (~ruined) & (walk.min(axis=1) <= -bankroll)
        ruined |= newly_ruined

        equity = walk[:, -1]
        equity[ruined] = -bankroll
        peak = np.maximum(running_peak[:, -1], equity)

        while (
            next_checkpoint < len(checkpoint_steps)
            and checkpoint_steps[next_checkpoint] <= done + chunk
        ):
            index = checkpoint_steps[next_checkpoint] - done - 1
            column = np.where(ruined, -bankroll, walk[:, index])
            checkpoints[:, next_checkpoint] = bankroll + column
            next_checkpoint += 1

        done += chunk

    # A loss below start can never exceed the bankroll: past that you are broke.
    worst_below_start = np.minimum(worst_below_start, bankroll)

    result = SimResult(
        allocation=allocation,
        hands=hands,
        paths=paths,
        bankroll_eur=bankroll,
        ruin_probability=float(ruined.mean()),
        max_drawdown=max_dd,
        loss_below_start=worst_below_start,
        final_bankroll=np.maximum(bankroll + equity, 0.0),
        checkpoint_hands=checkpoint_steps * _HANDS_PER_STEP,
        checkpoint_bankroll=checkpoints,
    )
    result._hours = hands / (config.tables * config.hands_per_hour_per_table)
    return result
