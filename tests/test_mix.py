"""Tests for the table-allocation optimiser."""

from __future__ import annotations

import unittest

from shotopt import mix
from shotopt.analysis import build_reports
from shotopt.config import Config, Stake


def _config(**overrides) -> Config:
    defaults = dict(
        bankroll_eur=5000.0,
        tables=6,
        ruin_tolerance=0.01,
        stakes=(
            Stake("50NL", 0.5, 7.0, 95.0),
            Stake("100NL", 1.0, 5.5, 92.0),
            Stake("200NL", 2.0, 3.5, 90.0),
        ),
    )
    defaults.update(overrides)
    return Config(**defaults)


class TestEnumeration(unittest.TestCase):
    def test_counts_every_composition(self):
        # C(T + S - 1, S - 1) = C(8, 2) = 28 for 6 tables over 3 stakes.
        self.assertEqual(len(list(mix.enumerate_allocations(6, (6, 6, 6)))), 28)

    def test_every_allocation_uses_all_the_tables(self):
        for counts in mix.enumerate_allocations(6, (6, 6, 6)):
            self.assertEqual(sum(counts), 6)

    def test_no_duplicates(self):
        allocations = list(mix.enumerate_allocations(7, (7, 7, 7)))
        self.assertEqual(len(allocations), len(set(allocations)))

    def test_caps_are_respected(self):
        for counts in mix.enumerate_allocations(6, (6, 2, 6)):
            self.assertLessEqual(counts[1], 2)

    def test_a_zero_cap_excludes_a_stake_entirely(self):
        for counts in mix.enumerate_allocations(6, (6, 0, 6)):
            self.assertEqual(counts[1], 0)

    def test_impossible_caps_raise(self):
        with self.assertRaises(mix.AllocationLimit):
            list(mix.enumerate_allocations(10, (2, 2, 2)))

    def test_blow_up_is_refused_rather_than_attempted(self):
        with self.assertRaises(mix.AllocationLimit):
            list(mix.enumerate_allocations(60, tuple([60] * 12)))

    def test_max_tables_of_zero_is_a_cap_not_an_absence(self):
        # The truthiness trap: 0 must mean "no seats here", not "no limit".
        config = _config(
            stakes=(
                Stake("50NL", 0.5, 7.0, 95.0),
                Stake("100NL", 1.0, 5.5, 92.0, max_tables=0),
                Stake("200NL", 2.0, 3.5, 90.0),
            )
        )
        for allocation in mix.all_allocations(config):
            self.assertEqual(allocation.counts[1], 0)


class TestEvaluation(unittest.TestCase):
    def test_a_single_stake_mix_reproduces_that_stakes_own_report(self):
        """The load-bearing cross-check between mix.py and analysis.py.

        Putting every table on one stake must give exactly the same risk of ruin
        as that stake's row in the per-stake report. The two are computed by
        completely different routes - one in big blinds, one in euros - so this
        catches a unit error in either.
        """
        for correlation in (0.0, 0.2):
            config = _config(table_correlation=correlation)
            reports = {r.stake.name: r for r in build_reports(config)}
            for index, stake in enumerate(config.stakes):
                counts = tuple(
                    config.tables if i == index else 0 for i in range(len(config.stakes))
                )
                allocation = mix.evaluate(counts, config)
                self.assertAlmostEqual(
                    allocation.risk_of_ruin, reports[stake.name].risk_of_ruin, places=10,
                    msg=f"{stake.name} at rho={correlation}",
                )
                self.assertAlmostEqual(
                    allocation.eur_per_hour, reports[stake.name].eur_per_hour, places=8
                )

    def test_hourly_is_a_weighted_blend_of_the_pure_mixes(self):
        config = _config(tables=6)
        pure_low = mix.evaluate((6, 0, 0), config).eur_per_hour
        pure_high = mix.evaluate((0, 0, 6), config).eur_per_hour
        blend = mix.evaluate((3, 0, 3), config).eur_per_hour
        self.assertAlmostEqual(blend, (pure_low + pure_high) / 2)

    def test_a_mix_sits_between_its_pure_extremes_on_risk(self):
        config = _config()
        low = mix.evaluate((6, 0, 0), config).risk_of_ruin
        high = mix.evaluate((0, 0, 6), config).risk_of_ruin
        blend = mix.evaluate((3, 0, 3), config).risk_of_ruin
        self.assertLess(low, blend)
        self.assertLess(blend, high)

    def test_label_reads_as_a_table_plan(self):
        self.assertEqual(mix.evaluate((4, 0, 2), _config()).label, "4x 50NL + 2x 200NL")

    def test_correlation_raises_risk(self):
        plain = mix.evaluate((3, 3, 0), _config())
        correlated = mix.evaluate((3, 3, 0), _config(table_correlation=0.2))
        self.assertGreater(correlated.risk_of_ruin, plain.risk_of_ruin)

    def test_rejects_a_miscounted_allocation(self):
        with self.assertRaises(ValueError):
            mix.evaluate((1, 1), _config())
        with self.assertRaises(ValueError):
            mix.evaluate((0, 0, 0), _config())


class TestOptimisation(unittest.TestCase):
    def test_best_is_inside_tolerance_and_beats_every_other_inside_it(self):
        allocations = mix.all_allocations(_config())
        best = mix.best_allocation(allocations)
        self.assertTrue(best.within_tolerance)
        for allocation in allocations:
            if allocation.within_tolerance:
                self.assertLessEqual(allocation.eur_per_hour, best.eur_per_hour + 1e-9)

    def test_the_optimum_beats_or_matches_every_single_stake_option(self):
        # The point of the whole module: a mix should never be worse than the
        # best pure allocation, because the pure ones are in the search space.
        config = _config()
        allocations = mix.all_allocations(config)
        best = mix.best_allocation(allocations)
        pure = [a for a in allocations if sum(1 for c in a.counts if c) == 1]
        best_pure = max(
            (a for a in pure if a.within_tolerance), key=lambda a: a.eur_per_hour, default=None
        )
        self.assertIsNotNone(best_pure)
        self.assertGreaterEqual(best.eur_per_hour, best_pure.eur_per_hour)

    def test_none_when_nothing_clears(self):
        allocations = mix.all_allocations(_config(bankroll_eur=200.0, ruin_tolerance=1e-6))
        self.assertIsNone(mix.best_allocation(allocations))

    def test_a_bigger_bankroll_never_reduces_the_optimum(self):
        earnings = []
        for bankroll in (3000.0, 10_000.0, 40_000.0, 200_000.0):
            best = mix.best_allocation(mix.all_allocations(_config(bankroll_eur=bankroll)))
            earnings.append(best.eur_per_hour if best else 0.0)
        self.assertEqual(earnings, sorted(earnings))

    def test_a_looser_tolerance_never_reduces_the_optimum(self):
        tight = mix.best_allocation(mix.all_allocations(_config(ruin_tolerance=0.005)))
        loose = mix.best_allocation(mix.all_allocations(_config(ruin_tolerance=0.20)))
        self.assertGreaterEqual(loose.eur_per_hour, tight.eur_per_hour)


class TestFrontier(unittest.TestCase):
    def test_frontier_is_monotone_in_both_axes(self):
        edge = mix.frontier(mix.all_allocations(_config()))
        risks = [a.risk_of_ruin for a in edge]
        earnings = [a.eur_per_hour for a in edge]
        self.assertEqual(risks, sorted(risks))
        self.assertEqual(earnings, sorted(earnings))

    def test_nothing_dominates_a_frontier_point(self):
        allocations = mix.all_allocations(_config())
        for point in mix.frontier(allocations):
            for other in allocations:
                dominates = (
                    other.eur_per_hour > point.eur_per_hour
                    and other.risk_of_ruin < point.risk_of_ruin
                )
                self.assertFalse(dominates, f"{other.label} dominates {point.label}")

    def test_the_best_allocation_is_on_the_frontier(self):
        allocations = mix.all_allocations(_config())
        best = mix.best_allocation(allocations)
        self.assertIn(best.counts, {a.counts for a in mix.frontier(allocations)})


class TestMarginalStep(unittest.TestCase):
    def test_moves_exactly_one_table_up_one_rung(self):
        config = _config()
        allocation = mix.evaluate((3, 3, 0), config)
        stepped, gained, added = mix.marginal_step_up(allocation, config)
        self.assertEqual(stepped.counts, (3, 2, 1))
        self.assertEqual(sum(stepped.counts), config.tables)
        self.assertGreater(added, 0)
        self.assertGreater(gained, 0)

    def test_none_when_everything_is_already_at_the_top(self):
        config = _config()
        allocation = mix.evaluate((0, 0, 6), config)
        self.assertIsNone(mix.marginal_step_up(allocation, config))


if __name__ == "__main__":
    unittest.main()
