"""Tests for the Monte Carlo.

The important one is `test_reproduces_the_closed_form`: where the analytic model
has an answer, the simulation must agree with it. Everything else is guarding
the bookkeeping.
"""

from __future__ import annotations

import math
import unittest

import numpy as np

from shotopt import mix, ruin, sim
from shotopt.config import Config, Stake


def _config(**overrides) -> Config:
    defaults = dict(
        bankroll_eur=5000.0,
        tables=12,
        ruin_tolerance=0.01,
        stakes=(
            Stake("100NL", 1.0, 7.46, 92.0),
            Stake("200NL", 2.0, 4.32, 92.0),
        ),
    )
    defaults.update(overrides)
    return Config(**defaults)


class TestSimulation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = _config()
        cls.allocation = mix.evaluate((4, 8), cls.config)
        cls.result = sim.simulate(cls.config, cls.allocation, hands=200_000, paths=4_000)

    def test_shapes_and_bounds(self):
        r = self.result
        self.assertEqual(len(r.max_drawdown), r.paths)
        self.assertEqual(len(r.final_bankroll), r.paths)
        self.assertTrue((r.final_bankroll >= 0).all())
        self.assertTrue((r.max_drawdown >= 0).all())

    def test_loss_below_start_never_exceeds_the_bankroll(self):
        # Past that you are broke, so a deeper figure would be meaningless.
        self.assertTrue((self.result.loss_below_start <= self.config.bankroll_eur + 1e-9).all())

    def test_peak_to_trough_is_never_shallower_than_loss_below_start(self):
        # The starting bankroll is one of the peaks, so the peak-to-trough
        # measure dominates the below-start one path by path, always.
        self.assertTrue(
            (self.result.max_drawdown >= self.result.loss_below_start - 1e-9).all()
        )

    def test_ruined_paths_stay_ruined(self):
        # Absorbing ruin: a busted lifetime must not trade its way back. Without
        # this the ruin rate stays honest but every percentile above it lies.
        r = self.result
        busted = r.loss_below_start >= self.config.bankroll_eur - 1e-9
        if busted.any():
            self.assertTrue((r.final_bankroll[busted] == 0).all())

    def test_reproduces_the_closed_form(self):
        """The anchor. Loss below start must match the analytic exponential.

        Run long enough for the finite-horizon figure to converge, then compare
        quantiles. Tolerance is loose (8%) because this is a sampled quantity,
        but a sign error or a units slip would miss by multiples.
        """
        allocation = self.allocation
        result = sim.simulate(
            self.config, allocation, hands=4_000_000, paths=6_000, seed=11
        )
        mean = allocation.mean_eur_per_100
        stdev = math.sqrt(allocation.variance_eur_per_100)
        for quantile in (0.5, 0.75, 0.9):
            simulated = float(np.percentile(result.loss_below_start, quantile * 100))
            exact = ruin.loss_below_start_quantile(mean, stdev, quantile)
            self.assertAlmostEqual(
                simulated / exact, 1.0, delta=0.08,
                msg=f"{quantile:.0%}: sim {simulated:,.0f} vs exact {exact:,.0f}",
            )

    def test_ruin_within_a_horizon_is_below_the_all_time_figure(self):
        # Finite time can only be kinder than forever.
        self.assertLessEqual(
            self.result.ruin_probability, self.allocation.risk_of_ruin + 0.005
        )

    def test_peak_to_trough_grows_with_the_horizon(self):
        """The property that makes an all-time peak-to-trough figure meaningless.

        A winning bankroll keeps setting new highs to fall from, so the worst
        drawdown has no limit - it just keeps growing with the time available.
        """
        short = sim.simulate(self.config, self.allocation, hands=200_000, paths=3_000, seed=5)
        long = sim.simulate(self.config, self.allocation, hands=2_000_000, paths=3_000, seed=5)
        self.assertGreater(
            float(np.percentile(long.max_drawdown, 50)),
            float(np.percentile(short.max_drawdown, 50)) * 1.15,
        )

    def test_loss_below_start_does_NOT_grow_with_the_horizon(self):
        """The mirror property: this one converges, which is why it has a formula."""
        short = sim.simulate(self.config, self.allocation, hands=500_000, paths=4_000, seed=5)
        long = sim.simulate(self.config, self.allocation, hands=5_000_000, paths=4_000, seed=5)
        a = float(np.percentile(short.loss_below_start, 90))
        b = float(np.percentile(long.loss_below_start, 90))
        self.assertAlmostEqual(b / a, 1.0, delta=0.10)

    def test_a_seed_makes_it_reproducible(self):
        a = sim.simulate(self.config, self.allocation, hands=100_000, paths=500, seed=42)
        b = sim.simulate(self.config, self.allocation, hands=100_000, paths=500, seed=42)
        self.assertTrue(np.array_equal(a.max_drawdown, b.max_drawdown))

    def test_rejects_nonsense_inputs(self):
        with self.assertRaises(ValueError):
            sim.simulate(self.config, self.allocation, hands=10)
        with self.assertRaises(ValueError):
            sim.simulate(self.config, self.allocation, paths=0)


LADDER = (
    Stake("50NL", 0.5, 8.18, 92.0),
    Stake("100NL", 1.0, 7.46, 92.0),
    Stake("200NL", 2.0, 4.32, 92.0),
    Stake("400NL", 4.0, 4.41, 92.0),
)


class TestStepUp(unittest.TestCase):
    """The two moves a player really makes, not an abstract search."""

    def setUp(self):
        self.config = _config(stakes=LADDER)
        self.best = mix.best_allocation(mix.all_allocations(self.config))
        self.options = mix.step_up_options(self.config, self.best)

    def test_every_move_keeps_the_table_count(self):
        for option in self.options:
            self.assertEqual(sum(option.allocation.counts), self.config.tables)

    def test_top_up_moves_one_table_off_the_highest_rung(self):
        highest = max(i for i, c in enumerate(self.best.counts) if c)
        option = next(o for o in self.options if o.label.startswith("Top up"))
        self.assertEqual(option.allocation.counts[highest], self.best.counts[highest] - 1)
        self.assertEqual(
            option.allocation.counts[highest + 1], self.best.counts[highest + 1] + 1
        )

    def test_bottom_up_moves_one_table_off_the_lowest_rung(self):
        lowest = min(i for i, c in enumerate(self.best.counts) if c)
        option = next(o for o in self.options if o.label.startswith("Bottom up"))
        self.assertEqual(option.allocation.counts[lowest], self.best.counts[lowest] - 1)
        self.assertEqual(
            option.allocation.counts[lowest + 1], self.best.counts[lowest + 1] + 1
        )

    def test_every_move_shifts_exactly_one_table(self):
        for option in self.options:
            moved = sum(
                abs(a - b) for a, b in zip(option.allocation.counts, self.best.counts)
            )
            self.assertEqual(moved, 2)  # one table leaves a rung, one arrives

    def test_the_two_moves_are_distinct(self):
        counts = {o.allocation.counts for o in self.options}
        self.assertEqual(len(counts), len(self.options))

    def test_both_moves_raise_risk_relative_to_the_optimum(self):
        # Moving up cannot be free: the optimum already took the best trade
        # available inside tolerance, so anything further costs risk.
        for option in self.options:
            self.assertGreater(option.ruin_multiple, 1.0)

    def test_deltas_are_measured_against_the_optimum(self):
        for option in self.options:
            self.assertAlmostEqual(
                option.eur_per_hour_delta,
                option.allocation.eur_per_hour - self.best.eur_per_hour,
            )

    def test_a_cap_blocks_the_move_it_would_break(self):
        capped = tuple(
            Stake(s.name, s.bb_eur, s.winrate_bb100, s.stdev_bb100, max_tables=0)
            if s.name == "400NL" else s
            for s in LADDER
        )
        config = _config(stakes=capped)
        best = mix.best_allocation(mix.all_allocations(config))
        for option in mix.step_up_options(config, best):
            self.assertEqual(option.allocation.counts[3], 0)

    def test_empty_when_already_at_the_top(self):
        config = _config(
            bankroll_eur=10_000_000.0,
            stakes=(Stake("100NL", 1.0, 7.46, 92.0), Stake("200NL", 2.0, 4.32, 92.0)),
        )
        best = mix.best_allocation(mix.all_allocations(config))
        self.assertEqual(best.counts[1], config.tables)
        self.assertEqual(mix.step_up_options(config, best), [])


class TestCurrentAllocation(unittest.TestCase):
    def test_apportions_hands_to_whole_tables(self):
        config = _config(
            tables=12,
            stakes=tuple(
                Stake(s.name, s.bb_eur, s.winrate_bb100, s.stdev_bb100, current_hands=h)
                for s, h in zip(LADDER, (23_082, 11_052, 13_760, 4_632))
            ),
        )
        current = mix.current_allocation(config)
        self.assertEqual(sum(current.counts), 12)
        self.assertEqual(current.counts, (5, 3, 3, 1))

    def test_largest_remainder_keeps_the_total_exact(self):
        """Naive rounding is the trap: three stakes at 1.4/1.4/1.2 tables each
        round to 1, and four tables become three."""
        config = _config(
            tables=4,
            stakes=tuple(
                Stake(s.name, s.bb_eur, s.winrate_bb100, s.stdev_bb100, current_hands=h)
                for s, h in zip(LADDER[:3], (35, 35, 30))
            ),
        )
        self.assertEqual(sum(mix.current_allocation(config).counts), 4)

    def test_none_without_any_current_hands(self):
        self.assertIsNone(mix.current_allocation(_config(stakes=LADDER)))

    def test_a_stake_never_played_gets_no_tables(self):
        config = _config(
            stakes=tuple(
                Stake(s.name, s.bb_eur, s.winrate_bb100, s.stdev_bb100, current_hands=h)
                for s, h in zip(LADDER, (10_000, 10_000, 0, 0))
            ),
        )
        current = mix.current_allocation(config)
        self.assertEqual(current.counts[2], 0)
        self.assertEqual(current.counts[3], 0)


if __name__ == "__main__":
    unittest.main()
