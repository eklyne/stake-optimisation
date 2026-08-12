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


class TestRakeback(unittest.TestCase):
    """Rakeback is money without variance - the tests pin exactly that."""

    def _with(self, pct: float) -> Config:
        return _config(
            rakeback_pct=pct,
            stakes=(
                Stake("100NL", 1.0, 5.5, 92.0, rake_bb100=8.0),
                Stake("200NL", 2.0, 3.5, 90.0, rake_bb100=6.5),
            ),
        )

    def test_it_raises_the_mean(self):
        without = mix.evaluate((3, 3), self._with(0.0))
        with_rb = mix.evaluate((3, 3), self._with(0.3))
        self.assertGreater(with_rb.mean_eur_per_100, without.mean_eur_per_100)

    def test_it_does_NOT_raise_the_variance(self):
        # The load-bearing property. Rakeback is a rebate on volume, not a
        # gamble; if it ever moved the variance, every risk number downstream
        # would be quietly wrong in the safe-looking direction.
        without = mix.evaluate((3, 3), self._with(0.0))
        with_rb = mix.evaluate((3, 3), self._with(0.3))
        self.assertAlmostEqual(with_rb.variance_eur_per_100, without.variance_eur_per_100)

    def test_it_therefore_lowers_risk_of_ruin(self):
        without = mix.evaluate((3, 3), self._with(0.0))
        with_rb = mix.evaluate((3, 3), self._with(0.3))
        self.assertLess(with_rb.risk_of_ruin, without.risk_of_ruin)

    def test_the_amount_is_the_stated_share_of_rake(self):
        screens = {s.stake.name: s for s in mix.screen_stakes(self._with(0.25))}
        # 100NL: 5.5 + 0.25*8.0 = 7.5 bb/100, at EUR1/bb.
        self.assertAlmostEqual(screens["100NL"].mean_eur_per_100, 7.5)

    def test_zero_rakeback_is_inert(self):
        plain = _config(
            stakes=(Stake("100NL", 1.0, 5.5, 92.0), Stake("200NL", 2.0, 3.5, 90.0))
        )
        self.assertAlmostEqual(
            mix.evaluate((3, 3), self._with(0.0)).mean_eur_per_100,
            mix.evaluate((3, 3), plain).mean_eur_per_100,
        )

    def test_a_stake_with_no_rake_figure_simply_earns_none(self):
        config = _config(
            rakeback_pct=0.3,
            stakes=(
                Stake("100NL", 1.0, 5.5, 92.0, rake_bb100=8.0),
                Stake("200NL", 2.0, 3.5, 90.0),  # no rake_bb100 supplied
            ),
        )
        screens = {s.stake.name: s for s in mix.screen_stakes(config)}
        self.assertAlmostEqual(screens["200NL"].mean_eur_per_100, 7.0)  # 3.5 * 2, unchanged
        self.assertAlmostEqual(screens["100NL"].mean_eur_per_100, 7.9)  # 5.5 + 2.4

    def test_it_can_change_which_stakes_are_redundant(self):
        # Rake falls in bb terms as stakes rise, so rakeback is worth most at the
        # bottom - enough here to lift the lower stake past the higher one.
        stakes = (
            Stake("100NL", 1.0, 4.0, 92.0, rake_bb100=10.0),
            Stake("200NL", 2.0, 2.2, 92.0, rake_bb100=3.0),
        )
        without = {s.stake.name: s.kept for s in mix.screen_stakes(_config(stakes=stakes))}
        with_rb = {
            s.stake.name: s.kept
            for s in mix.screen_stakes(_config(stakes=stakes, rakeback_pct=0.5))
        }
        self.assertTrue(without["200NL"])  # 4.40 EUR/100 beats 100NL's 4.00
        self.assertFalse(with_rb["200NL"])  # 5.90 vs 100NL's 9.00 - now dominated


class TestOptimisation(unittest.TestCase):
    def test_best_is_inside_tolerance_and_beats_every_other_inside_it(self):
        config = _config()
        allocations = mix.all_allocations(config)
        best = mix.best_allocation(allocations, config)
        self.assertTrue(best.within_ruin_tolerance)
        for allocation in allocations:
            if allocation.within_ruin_tolerance:
                self.assertLessEqual(allocation.eur_per_hour, best.eur_per_hour + 1e-9)

    def test_the_optimum_beats_or_matches_every_single_stake_option(self):
        # The point of the whole module: a mix should never be worse than the
        # best pure allocation, because the pure ones are in the search space.
        config = _config()
        allocations = mix.all_allocations(config)
        best = mix.best_allocation(allocations, config)
        pure = [a for a in allocations if sum(1 for c in a.counts if c) == 1]
        best_pure = max(
            (a for a in pure if a.within_ruin_tolerance), key=lambda a: a.eur_per_hour, default=None
        )
        self.assertIsNotNone(best_pure)
        self.assertGreaterEqual(best.eur_per_hour, best_pure.eur_per_hour)

    def test_none_when_nothing_clears(self):
        config = _config(bankroll_eur=200.0, ruin_tolerance=1e-6)
        self.assertIsNone(mix.best_allocation(mix.all_allocations(config), config))

    def test_a_bigger_bankroll_never_reduces_the_optimum(self):
        earnings = []
        for bankroll in (3000.0, 10_000.0, 40_000.0, 200_000.0):
            config = _config(bankroll_eur=bankroll)
            best = mix.best_allocation(mix.all_allocations(config), config)
            earnings.append(best.eur_per_hour if best else 0.0)
        self.assertEqual(earnings, sorted(earnings))

    def test_a_looser_tolerance_never_reduces_the_optimum(self):
        def solve(tolerance):
            config = _config(ruin_tolerance=tolerance)
            return mix.best_allocation(mix.all_allocations(config), config)

        self.assertGreaterEqual(solve(0.20).eur_per_hour, solve(0.005).eur_per_hour)


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
        config = _config()
        allocations = mix.all_allocations(config)
        best = mix.best_allocation(allocations, config)
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

    def test_never_steps_into_a_redundant_stake(self):
        # A "move up" into a dominated stake is worse on BOTH axes - not a
        # trade-off to price, just a mistake. It should skip to the next real
        # stake, or report that there is nowhere to go.
        config = _config(
            stakes=(
                Stake("100NL", 1.0, 5.5, 92.0),
                Stake("200NL", 2.0, 3.5, 90.0),
                Stake("400NL", 4.0, 0.5, 90.0),  # 2.00 EUR/100 vs 200NL's 7.00
            )
        )
        dominated = {i for i, s in enumerate(mix.screen_stakes(config)) if not s.kept}
        self.assertIn(2, dominated)
        step = mix.marginal_step_up(mix.evaluate((3, 3, 0), config), config)
        stepped, gained, _ = step
        self.assertEqual(stepped.counts[2], 0)
        self.assertGreater(gained, 0)

    def test_respects_a_cap_on_the_target(self):
        config = _config(
            stakes=(
                Stake("50NL", 0.5, 7.0, 95.0),
                Stake("100NL", 1.0, 5.5, 92.0),
                Stake("200NL", 2.0, 3.5, 90.0, max_tables=2),
            )
        )
        allocation = mix.evaluate((2, 2, 2), config)
        stepped, _, _ = mix.marginal_step_up(allocation, config)
        self.assertLessEqual(stepped.counts[2], 2)


class TestStakeScreen(unittest.TestCase):
    def test_a_higher_stake_earning_less_is_ruled_out(self):
        # The case the user cares about: pay more rake and more variance for
        # less money. 600NL at 1bb/100 makes 6 EUR/100 against 200NL's 7.
        config = _config(
            stakes=(
                Stake("200NL", 2.0, 3.5, 90.0),
                Stake("600NL", 6.0, 1.0, 88.0),
            )
        )
        screens = mix.screen_stakes(config)
        self.assertTrue(screens[0].kept)
        self.assertFalse(screens[1].kept)
        self.assertEqual(screens[1].dominated_by.name, "200NL")

    def test_a_lower_earning_stake_with_lower_variance_survives(self):
        # The half of the rule that EUR/hour alone would get wrong: 50NL earns
        # less than 100NL but is also less volatile, so it is a real low-risk
        # option and belongs on the frontier.
        screens = {s.stake.name: s for s in mix.screen_stakes(_config())}
        self.assertTrue(screens["50NL"].kept)
        self.assertLess(screens["50NL"].mean_eur_per_100, screens["100NL"].mean_eur_per_100)
        self.assertLess(screens["50NL"].stdev_eur_per_100, screens["100NL"].stdev_eur_per_100)

    def test_a_capped_dominator_cannot_rule_anything_out(self):
        # If 200NL can only give you 2 seats, it cannot absorb 600NL's tables,
        # so 600NL still has a job and must be kept.
        config = _config(
            tables=6,
            stakes=(
                Stake("200NL", 2.0, 3.5, 90.0, max_tables=2),
                Stake("600NL", 6.0, 1.0, 88.0),
            ),
        )
        self.assertTrue(all(s.kept for s in mix.screen_stakes(config)))

    def test_nothing_is_ruled_out_in_a_well_behaved_ladder(self):
        self.assertTrue(all(s.kept for s in mix.screen_stakes(_config())))

    def test_a_held_out_stake_says_so_rather_than_claiming_an_economic_verdict(self):
        # max_tables = 0 is the user's choice, not something the tool worked out.
        # Reporting it as "redundant" would put words in their mouth - and here
        # the stake is not redundant at all, it is the best earner on paper.
        config = _config(
            stakes=(
                Stake("200NL", 2.0, 3.5, 90.0),
                Stake("1KNL", 10.0, 60.0, 92.0, hands=127, max_tables=0),
            )
        )
        screens = mix.screen_stakes(config)
        self.assertTrue(screens[0].kept)
        self.assertFalse(screens[1].kept)
        self.assertIn("max_tables", screens[1].excluded_reason)
        self.assertIsNone(screens[1].dominated_by)

    def test_a_held_out_stake_gets_no_tables(self):
        config = _config(
            stakes=(
                Stake("200NL", 2.0, 3.5, 90.0),
                Stake("1KNL", 10.0, 60.0, 92.0, hands=127, max_tables=0),
            )
        )
        for allocation in mix.all_allocations(config):
            self.assertEqual(allocation.counts[1], 0)

    def test_pruning_cannot_change_the_frontier(self):
        """The property that licenses pruning as more than a display filter.

        Dropping a dominated stake must give byte-identical frontier and optimum,
        because every allocation using it is beaten on both axes by moving those
        tables to the dominator.
        """
        config = _config(
            tables=8,
            stakes=(
                Stake("50NL", 0.5, 7.0, 95.0),
                Stake("100NL", 1.0, 5.5, 92.0),
                Stake("200NL", 2.0, 3.5, 90.0),
                Stake("600NL", 6.0, 1.0, 88.0),  # dominated by 200NL
                Stake("1KNL", 10.0, 0.5, 88.0),  # dominated by 100NL
            ),
        )
        pruned = mix.all_allocations(config, prune=True)
        full = mix.all_allocations(config, prune=False)
        self.assertLess(len(pruned), len(full))

        self.assertEqual(
            [a.counts for a in mix.frontier(pruned)],
            [a.counts for a in mix.frontier(full)],
        )
        self.assertEqual(
            mix.best_allocation(pruned, config).counts, mix.best_allocation(full, config).counts
        )


if __name__ == "__main__":
    unittest.main()
