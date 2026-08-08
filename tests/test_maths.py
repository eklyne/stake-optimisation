"""Tests for the closed-form layer.

These are chosen to catch a real algebra slip rather than to hit line coverage.
Several assert identities that are quotable results in their own right - half
Kelly keeping three quarters of the growth, full Kelly making a 50% drawdown a
coin flip - so if the maths drifts, a claim the README makes out loud breaks
with it.

Run: py -m unittest discover -s tests
"""

from __future__ import annotations

import math
import unittest

from shotopt import estimation, kelly, rates, ruin


class TestKelly(unittest.TestCase):
    def test_optimal_bankroll_is_variance_over_edge(self):
        # mu=5, sigma=90 -> 8100/5 = 1620bb = 16.2 buy-ins at full Kelly.
        self.assertAlmostEqual(kelly.optimal_bankroll_bb(5.0, 90.0), 1620.0)

    def test_half_kelly_needs_double_the_bankroll(self):
        full = kelly.required_bankroll_bb(5.0, 90.0, 1.0)
        half = kelly.required_bankroll_bb(5.0, 90.0, 0.5)
        self.assertAlmostEqual(half, 2.0 * full)

    def test_supported_stake_inverts_required_bankroll(self):
        bb = kelly.optimal_bb_eur(10_000.0, 5.0, 90.0, 0.5)
        needed = kelly.required_bankroll_bb(5.0, 90.0, 0.5) * bb
        self.assertAlmostEqual(needed, 10_000.0)

    def test_half_kelly_keeps_three_quarters_of_the_growth(self):
        full = kelly.fractional_growth(5.0, 90.0, 1.0)
        half = kelly.fractional_growth(5.0, 90.0, 0.5)
        self.assertAlmostEqual(half / full, 0.75)

    def test_half_kelly_carries_a_quarter_of_the_variance(self):
        self.assertAlmostEqual(kelly.fractional_variance_ratio(0.5), 0.25)

    def test_full_kelly_growth_matches_closed_form(self):
        self.assertAlmostEqual(kelly.growth_rate(5.0, 90.0), 25.0 / (2 * 8100.0))
        self.assertAlmostEqual(kelly.fractional_growth(5.0, 90.0, 1.0), kelly.growth_rate(5.0, 90.0))

    def test_double_kelly_earns_nothing(self):
        self.assertAlmostEqual(kelly.fractional_growth(5.0, 90.0, 2.0), 0.0)

    def test_overbetting_hurts_more_than_underbetting(self):
        under = kelly.fractional_growth(5.0, 90.0, 0.6)
        over = kelly.fractional_growth(5.0, 90.0, 1.4)
        self.assertAlmostEqual(under, over)  # symmetric about k=1...
        self.assertLess(
            kelly.rescaled_drawdown_probability(0.5, 0.6),
            kelly.rescaled_drawdown_probability(0.5, 1.4),
        )  # ...but the risk is not, which is the whole argument

    def test_full_kelly_drawdown_is_the_fraction_itself(self):
        for fraction in (0.1, 0.5, 0.9):
            self.assertAlmostEqual(kelly.rescaled_drawdown_probability(fraction, 1.0), fraction)

    def test_half_kelly_drawdown_is_the_cube(self):
        self.assertAlmostEqual(kelly.rescaled_drawdown_probability(0.5, 0.5), 0.125)

    def test_kelly_is_undefined_for_a_loser(self):
        with self.assertRaises(ValueError):
            kelly.optimal_bankroll_bb(-1.0, 90.0)
        with self.assertRaises(ValueError):
            kelly.optimal_bankroll_bb(0.0, 90.0)

    def test_rescaled_drawdown_rejects_k_at_or_above_two(self):
        with self.assertRaises(ValueError):
            kelly.rescaled_drawdown_probability(0.5, 2.0)


class TestRuin(unittest.TestCase):
    def test_matches_the_closed_form(self):
        self.assertAlmostEqual(
            ruin.risk_of_ruin(5.0, 90.0, 1620.0), math.exp(-2 * 5.0 * 1620.0 / 8100.0)
        )

    def test_bankroll_for_ruin_round_trips(self):
        for tolerance in (0.001, 0.01, 0.05, 0.25):
            bankroll = ruin.bankroll_for_ruin(5.0, 90.0, tolerance)
            self.assertAlmostEqual(ruin.risk_of_ruin(5.0, 90.0, bankroll), tolerance)

    def test_ruin_falls_as_the_bankroll_grows(self):
        values = [ruin.risk_of_ruin(5.0, 90.0, b) for b in (500, 1000, 2000, 10_000)]
        self.assertEqual(values, sorted(values, reverse=True))
        self.assertLess(values[-1], 1e-5)

    def test_a_losing_player_busts_with_certainty(self):
        self.assertEqual(ruin.risk_of_ruin(0.0, 90.0, 1_000_000.0), 1.0)
        self.assertEqual(ruin.risk_of_ruin(-3.0, 90.0, 1_000_000.0), 1.0)

    def test_no_finite_bankroll_saves_a_loser(self):
        with self.assertRaises(ValueError):
            ruin.bankroll_for_ruin(-1.0, 90.0, 0.01)

    def test_full_drawdown_is_ruin(self):
        self.assertAlmostEqual(
            ruin.drawdown_probability(5.0, 90.0, 1620.0, 1.0),
            ruin.risk_of_ruin(5.0, 90.0, 1620.0),
        )

    def test_a_partial_drawdown_is_likelier_than_ruin(self):
        deep = ruin.drawdown_probability(5.0, 90.0, 3000.0, 1.0)
        shallow = ruin.drawdown_probability(5.0, 90.0, 3000.0, 0.5)
        self.assertGreater(shallow, deep)

    def test_effective_stdev_is_inert_when_uncorrelated(self):
        self.assertAlmostEqual(ruin.effective_stdev(90.0, 12, 0.0), 90.0)
        self.assertAlmostEqual(ruin.effective_stdev(90.0, 1, 0.5), 90.0)

    def test_correlated_tables_raise_effective_stdev(self):
        self.assertGreater(
            ruin.effective_stdev(90.0, 12, 0.1), ruin.effective_stdev(90.0, 4, 0.1)
        )
        # rho=1 collapses the tables into one bet: sigma * sqrt(tables)
        self.assertAlmostEqual(ruin.effective_stdev(90.0, 4, 1.0), 180.0)


class TestEstimation(unittest.TestCase):
    def test_stderr_falls_as_the_root_of_volume(self):
        small = estimation.winrate_stderr(90.0, 10_000)
        large = estimation.winrate_stderr(90.0, 40_000)
        self.assertAlmostEqual(small / large, 2.0)

    def test_stderr_closed_form(self):
        self.assertAlmostEqual(estimation.winrate_stderr(90.0, 10_000), 9.0)

    def test_ci_brackets_the_estimate(self):
        low, high = estimation.winrate_ci(5.0, 90.0, 100_000)
        self.assertLess(low, 5.0)
        self.assertGreater(high, 5.0)
        self.assertAlmostEqual((low + high) / 2, 5.0)

    def test_precision_is_quadratic_in_volume(self):
        coarse = estimation.hands_for_precision(90.0, 2.0)
        fine = estimation.hands_for_precision(90.0, 1.0)
        self.assertAlmostEqual(fine / coarse, 4.0)

    def test_shaded_winrate_is_pessimistic_and_converges(self):
        thin = estimation.shaded_winrate(5.0, 90.0, 10_000)
        thick = estimation.shaded_winrate(5.0, 90.0, 1_000_000)
        self.assertLess(thin, thick)  # more volume, smaller shade
        self.assertLess(thick, 5.0)  # but never optimistic
        # Convergence is slow enough to be worth pinning down: even a MILLION
        # hands leaves the shade at 0.9 bb/100, which is most of a stake move.
        self.assertAlmostEqual(5.0 - thick, 0.9)
        self.assertAlmostEqual(5.0 - estimation.shaded_winrate(5.0, 90.0, 100_000_000), 0.09)


class TestRates(unittest.TestCase):
    def test_hourly_scales_linearly_in_tables(self):
        one = rates.eur_per_hour(5.0, 1.0, 1, 75.0)
        twelve = rates.eur_per_hour(5.0, 1.0, 12, 75.0)
        self.assertAlmostEqual(twelve, 12 * one)

    def test_hourly_closed_form(self):
        # 5bb/100 at EUR1/bb, 12 tables x 75 hands = 900 hands/hr -> 45bb -> EUR45
        self.assertAlmostEqual(rates.eur_per_hour(5.0, 1.0, 12, 75.0), 45.0)

    def test_haircut_charges_only_the_extra_tables(self):
        self.assertAlmostEqual(rates.effective_winrate(6.0, 1, 0.2), 6.0)
        self.assertAlmostEqual(rates.effective_winrate(6.0, 6, 0.2), 5.0)

    def test_zero_haircut_is_inert(self):
        self.assertAlmostEqual(rates.effective_winrate(6.0, 24, 0.0), 6.0)


class TestCrossChecks(unittest.TestCase):
    """The relations that tie the modules together - where a sign error hides."""

    def test_kelly_bankroll_implies_a_fixed_ruin_probability(self):
        # At the full-Kelly bankroll B* = sigma^2/mu, the exponent is exactly -2,
        # so risk of ruin is e^-2 ~ 13.5% REGARDLESS of the win rate or variance.
        # That constant is the cleanest statement of why full Kelly is too hot.
        for winrate, stdev in ((5.0, 90.0), (2.0, 110.0), (12.0, 70.0)):
            bankroll = kelly.optimal_bankroll_bb(winrate, stdev)
            self.assertAlmostEqual(ruin.risk_of_ruin(winrate, stdev, bankroll), math.exp(-2.0))

    def test_half_kelly_bankroll_implies_e_to_the_minus_four(self):
        bankroll = kelly.required_bankroll_bb(5.0, 90.0, 0.5)
        self.assertAlmostEqual(ruin.risk_of_ruin(5.0, 90.0, bankroll), math.exp(-4.0))

    def test_typical_inputs_land_near_the_folklore(self):
        # Half Kelly at a 5bb/100 win rate and 90bb/100 sigma should land in the
        # same neighbourhood as the conventional 30-buy-in rule. If this test
        # starts failing, either the maths broke or the folklore was never a
        # proxy for it - and the first is far likelier.
        buyins = kelly.required_bankroll_bb(5.0, 90.0, 0.5) / 100.0
        self.assertTrue(25 <= buyins <= 40, f"got {buyins:.1f} buy-ins")


if __name__ == "__main__":
    unittest.main()
