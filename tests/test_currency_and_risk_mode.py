"""Tests for the display currency and the selectable risk rule.

Two features that pull in opposite directions and are easy to get subtly wrong:

* The CURRENCY must change nothing but the presentation. The failure mode is not
  a crash - it is a run that looks fine and is wrong by the FX rate, or wrong only
  in the columns nobody checked. So the tests here pin the identity case
  (`fx = 1.0` must be byte-identical to EUR) and the linearity of everything else.
* The RISK MODE must change the answer, and only through the rule. The failure
  mode is a downswing tolerance that silently falls back to ruin, or a walk that
  returns a mix the rule would reject.
"""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from shotopt import export, mix, sim, tolerance
from shotopt.config import Config, ConfigError, Stake, load_config
from shotopt.money import EUR, Currency

GBP = Currency("GBP", 1.16)


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


def _write(text: str) -> Path:
    handle = tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False, encoding="utf-8")
    handle.write(text)
    handle.close()
    return Path(handle.name)


_TOML = """
bankroll = 5000
tables = 6

[risk]
ruin_tolerance = 0.01

[[stake]]
name = "100NL"
bb_eur = 1.0
winrate_bb100 = 5.0
stdev_bb100 = 90.0
hands = 100000
"""


# --------------------------------------------------------------------------- #
# Currency
# --------------------------------------------------------------------------- #
class TestCurrencyMaths(unittest.TestCase):
    def test_the_rate_reads_the_way_the_config_documents_it(self):
        # eur_per_unit is the EUROS IN ONE UNIT, so GBP figures are SMALLER than
        # the euro ones they came from. Inverting this is the whole bug class.
        self.assertAlmostEqual(GBP.to_eur(1000.0), 1160.0)
        self.assertAlmostEqual(GBP.from_eur(1160.0), 1000.0)
        self.assertLess(GBP.from_eur(1000.0), 1000.0)

    def test_round_trips(self):
        for amount in (1.0, 250.5, 10_000.0):
            self.assertAlmostEqual(GBP.from_eur(GBP.to_eur(amount)), amount)

    def test_eur_is_the_identity(self):
        self.assertTrue(EUR.is_base)
        self.assertEqual(EUR.to_eur(123.45), 123.45)
        self.assertEqual(EUR.from_eur(123.45), 123.45)
        self.assertIsNone(EUR.note())

    def test_formatting_carries_the_code(self):
        self.assertEqual(GBP.fmt(1160.0), "GBP 1,000")
        self.assertEqual(GBP.plain(1160.0), "1,000")
        self.assertEqual(GBP.axis("/ hour"), "GBP / hour")
        self.assertIn("1.16", GBP.note())


class TestCurrencyIsDisplayOnly(unittest.TestCase):
    """The core guarantee: the model does not know the currency exists."""

    def test_the_chosen_mix_is_identical_in_any_currency(self):
        eur = _config()
        gbp = _config(currency=GBP)
        self.assertEqual(
            mix.best_allocation(mix.all_allocations(eur), eur).counts,
            mix.best_allocation(mix.all_allocations(gbp), gbp).counts,
        )

    def test_internal_values_stay_in_euros(self):
        # `mean_eur_per_100` and friends keep their names AND their units, so a
        # reader of the allocation object is never guessing which it holds.
        eur = mix.evaluate((2, 2, 2), _config())
        gbp = mix.evaluate((2, 2, 2), _config(currency=GBP))
        self.assertAlmostEqual(eur.eur_per_hour, gbp.eur_per_hour)
        self.assertAlmostEqual(eur.mean_eur_per_100, gbp.mean_eur_per_100)
        self.assertAlmostEqual(eur.risk_of_ruin, gbp.risk_of_ruin)

    def test_a_unit_rate_is_byte_identical_to_euros(self):
        # The sharpest form of "display only": relabel the currency, keep the
        # rate at 1.0, and only the column HEADERS may differ.
        one_to_one = Currency("XXX", 1.0)
        rows_eur = self._frontier_rows(_config())
        rows_xxx = self._frontier_rows(_config(currency=one_to_one))
        self.assertEqual(
            [list(r.values()) for r in rows_eur], [list(r.values()) for r in rows_xxx]
        )

    def test_money_columns_scale_and_bb_columns_do_not(self):
        eur_rows = self._screen_rows(_config())
        gbp_rows = self._screen_rows(_config(currency=GBP))
        for eur_row, gbp_row in zip(eur_rows, gbp_rows):
            self.assertAlmostEqual(
                float(gbp_row["per_hour_gbp"]),
                float(eur_row["per_hour_eur"]) / 1.16,
                places=3,
            )
            # The edge itself is a poker quantity and must not move.
            self.assertEqual(gbp_row["winrate_bb100"], eur_row["winrate_bb100"])
            self.assertEqual(gbp_row["stdev_bb100"], eur_row["stdev_bb100"])
            self.assertEqual(gbp_row["bb_eur"], eur_row["bb_eur"])

    def _screen_rows(self, config):
        path = Path(tempfile.mkdtemp()) / "screen.csv"
        export.write_stake_screen(
            mix.screen_stakes(config), path, config.rakeback_pct, config.currency
        )
        return list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))

    def _frontier_rows(self, config):
        allocations = mix.all_allocations(config)
        path = Path(tempfile.mkdtemp()) / "frontier.csv"
        export.write_frontier(
            mix.frontier(allocations),
            config,
            mix.best_allocation(allocations, config),
            path,
        )
        return list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))


class TestChartsAreDrawnInDisplayUnits(unittest.TestCase):
    """The axis label is not the only thing that has to change.

    The bug this guards against renders perfectly: a y-axis reading "GBP / hour"
    over points still plotted in euros, with a direct label quoting the correct
    sterling figure next to a marker sitting at the euro height. Nothing errors,
    and the chart is 16% wrong.
    """

    def _line_ys(self, figure):
        """Every y value drawn on the figure's single axes, markers included."""
        ax = figure.axes[0]
        values = [y for line in ax.get_lines() for y in line.get_ydata()]
        for collection in ax.collections:
            values.extend(point[1] for point in collection.get_offsets())
        return values

    def test_the_ruin_frontier_plots_money_in_the_display_currency(self):
        from shotopt import charts

        eur = _config()
        gbp = _config(currency=GBP)
        top_eur = max(self._line_ys(charts.allocation_frontier_figure(eur)))
        top_gbp = max(self._line_ys(charts.allocation_frontier_figure(gbp)))
        self.assertAlmostEqual(top_gbp, top_eur / 1.16, places=6)

    def test_the_downswing_frontier_plots_both_axes_in_it(self):
        from shotopt import charts

        eur = _downswing(4000.0)
        gbp = _downswing(4000.0, currency=GBP)
        figure_eur = charts.allocation_frontier_downswing_figure(eur)
        figure_gbp = charts.allocation_frontier_downswing_figure(gbp)
        self.assertAlmostEqual(
            max(self._line_ys(figure_gbp)),
            max(self._line_ys(figure_eur)) / 1.16,
            places=6,
        )
        # x too - it is money on this chart, unlike the ruin one.
        xs_eur = [x for line in figure_eur.axes[0].get_lines() for x in line.get_xdata()]
        xs_gbp = [x for line in figure_gbp.axes[0].get_lines() for x in line.get_xdata()]
        self.assertAlmostEqual(max(xs_gbp), max(xs_eur) / 1.16, places=6)


class TestUnannotatedFrontier(unittest.TestCase):
    """The deck's version of the frontier charts carries no text of its own.

    Every word moved to the slide (`charts.frontier_notes`), so anything still
    written into the axes is duplication sitting on top of the data. The marks
    themselves must survive - a chart stripped of its callouts AND its points
    would pass a naive "no text" check while showing nothing.
    """

    def _both(self):
        """Both rules live and a current mix to mark - so every element the
        annotations used to describe is actually on the chart."""
        return _downswing(
            4000.0,
            risk_mode="both",
            stakes=(
                Stake("50NL", 0.5, 7.0, 95.0, current_hands=20_000),
                Stake("100NL", 1.0, 5.5, 92.0, current_hands=10_000),
                Stake("200NL", 2.0, 3.5, 90.0, current_hands=5_000),
            ),
        )

    def _bare(self, figure):
        ax = figure.axes[0]
        return [t.get_text() for t in ax.texts] + [ax.get_title()]

    def test_neither_chart_draws_a_label_or_a_title(self):
        from shotopt import charts

        config = self._both()
        for figure in (
            charts.allocation_frontier_figure(config, annotate=False),
            charts.allocation_frontier_downswing_figure(config, annotate=False),
        ):
            self.assertEqual([t for t in self._bare(figure) if t], [])

    def test_the_marks_are_still_there(self):
        from shotopt import charts

        ax = charts.allocation_frontier_figure(self._both(), annotate=False).axes[0]
        # Cloud, frontier, both limit lines, best and current.
        self.assertTrue(ax.collections)
        self.assertGreaterEqual(len(ax.get_lines()), 5)
        # The current mix is the same circle as the best one, in blue.
        markers = {
            (line.get_marker(), line.get_markersize(), line.get_color())
            for line in ax.get_lines() if line.get_linestyle() == "None"
        }
        self.assertIn(("o", 10, charts.STATUS_GOOD), markers)
        self.assertIn(("o", 10, charts.COL_CURRENT_MARK), markers)

    def test_the_labels_are_still_available_as_text(self):
        from shotopt import charts

        config = self._both()
        allocations = mix.all_allocations(config)
        best = mix.best_allocation(allocations, config)
        blocks = charts.frontier_notes(config, best, mix.current_allocation(config))
        headings = [heading for heading, _, _ in blocks]
        self.assertTrue(any("Best inside tolerance" in h for h in headings))
        self.assertTrue(any("playing now" in h for h in headings))
        self.assertIn(best.label, [line for _, _, lines in blocks for line in lines])

    def test_the_pair_figure_holds_both_charts(self):
        from shotopt import charts

        figure = charts.frontier_pair_figure(self._both())
        self.assertEqual(len(figure.axes), 2)
        left, right = figure.axes
        self.assertIn("Risk of ruin", left.get_xlabel())
        self.assertIn("downswing", right.get_xlabel().lower())


class TestDegenerateRuinAxis(unittest.TestCase):
    """A big enough bankroll drives every mix under the ruin floor.

    The old chart clamped all of them to the floor and drew a vertical stick of
    points on the left edge - which looks like a rendering fault but is really
    the axis having nothing to say. Autoscaling was not the fix: the spread runs
    eighty-odd decades, and an axis separating 1e-97 from 1e-11 invites reading a
    difference between two numbers that are both zero in any human sense.
    """

    def _fat(self):
        # 200 buy-ins of the biggest stake: ruin is nil for everything.
        return _config(bankroll_eur=400_000.0)

    def test_the_premise_holds(self):
        from shotopt import charts

        risks = [a.risk_of_ruin for a in mix.all_allocations(self._fat())]
        self.assertLess(max(risks), charts.RUIN_NEGLIGIBLE)

    def test_it_switches_to_the_earnings_spread(self):
        from shotopt import charts

        ax = charts.allocation_frontier_figure(self._fat()).axes[0]
        self.assertEqual(ax.get_xlabel(), self._fat().currency.axis("/ hour"))
        self.assertIn("cannot rank", " ".join(
            t.get_text() for t in ax.texts
        ))

    def test_a_normal_bankroll_still_gets_the_ruin_axis(self):
        from shotopt import charts

        ax = charts.allocation_frontier_figure(_config()).axes[0]
        self.assertIn("Risk of ruin", ax.get_xlabel())
        self.assertEqual(ax.get_xscale(), "log")

    def test_tiny_probabilities_are_quoted_as_round_odds(self):
        from shotopt import charts

        # Not "1 in 21,399,231,025" - the digits past the first are noise.
        self.assertEqual(charts._one_in(4.673e-11), "1 in 21 billion")
        self.assertEqual(charts._one_in(1e-7), "1 in 10 million")
        self.assertEqual(charts._one_in(0.01), "1 in 100")


class TestPanelScaling(unittest.TestCase):
    def test_the_hourly_panel_scales_off_the_measured_stakes(self):
        """It used to take a fixed 300 EUR ceiling.

        A constant cannot work here: it is a number in one currency at one table
        count, so on any other config it sits far above every bar and squashes
        the whole panel onto the floor.
        """
        from shotopt import charts

        config = _config()
        figure = charts.winrate_ci_figure(mix.screen_stakes(config), config)
        bars = [
            patch.get_y() + patch.get_height()
            for patch in figure.axes[1].patches
        ]
        ceiling = figure.axes[1].get_ylim()[1]
        # The tallest bar must occupy a real share of the panel, not a sliver.
        self.assertGreater(max(bars) / ceiling, 0.25)


class TestCurrencyConfig(unittest.TestCase):
    def test_defaults_to_euros(self):
        config = load_config(_write(_TOML))
        self.assertTrue(config.currency.is_base)
        self.assertEqual(config.bankroll_eur, 5000)

    def test_a_typed_bankroll_is_converted_on_the_way_in(self):
        config = load_config(
            _write(_TOML.replace("bankroll = 5000", 'currency = "GBP"\nfx_eur_per_unit = 1.16\nbankroll = 5000'))
        )
        self.assertEqual(config.currency.code, "GBP")
        self.assertAlmostEqual(config.bankroll_eur, 5800.0)

    def test_a_foreign_currency_needs_a_rate(self):
        with self.assertRaises(ConfigError) as caught:
            load_config(_write('currency = "GBP"\n' + _TOML))
        self.assertIn("fx_eur_per_unit", str(caught.exception))

    def test_a_rate_on_euros_is_rejected_rather_than_ignored(self):
        # Silently ignoring it would leave every figure out by the rate.
        with self.assertRaises(ConfigError):
            load_config(_write("fx_eur_per_unit = 1.16\n" + _TOML))

    def test_the_old_bankroll_key_names_its_replacement(self):
        with self.assertRaises(ConfigError) as caught:
            load_config(_write(_TOML.replace("bankroll = 5000", "bankroll_eur = 5000")))
        self.assertIn("bankroll", str(caught.exception))

    def test_a_top_level_ruin_tolerance_is_caught(self):
        with self.assertRaises(ConfigError) as caught:
            load_config(_write("ruin_tolerance = 0.01\n" + _TOML))
        self.assertIn("[risk]", str(caught.exception))


# --------------------------------------------------------------------------- #
# Risk mode
# --------------------------------------------------------------------------- #
def _downswing(amount, **overrides):
    settings = dict(
        risk_mode="downswing",
        downswing_amount_eur=amount,
        downswing_hands=100_000,
        downswing_probability=0.05,
    )
    settings.update(overrides)
    return _config(**settings)


class TestRiskModeConfig(unittest.TestCase):
    def test_downswing_mode_needs_an_amount(self):
        with self.assertRaises(ConfigError):
            _config(risk_mode="downswing")

    def test_an_unknown_mode_is_rejected(self):
        with self.assertRaises(ConfigError):
            _config(risk_mode="vibes")

    def test_ruin_tolerance_is_required_even_in_downswing_mode(self):
        # It is still reported and charted, so it is not optional.
        with self.assertRaises(ConfigError) as caught:
            load_config(_write(_TOML.replace("ruin_tolerance = 0.01", "mode = 'downswing'")))
        self.assertIn("ruin_tolerance", str(caught.exception))

    def test_the_amount_is_read_in_the_display_currency(self):
        config = load_config(_write(
            'currency = "GBP"\nfx_eur_per_unit = 1.16\n'
            + _TOML.replace(
                "ruin_tolerance = 0.01",
                'mode = "downswing"\nruin_tolerance = 0.01\n'
                "downswing_amount = 1000\ndownswing_hands = 100000\n"
                "downswing_probability = 0.05",
            )
        ))
        self.assertAlmostEqual(config.downswing_amount_eur, 1160.0)


class TestDownswingTolerance(unittest.TestCase):
    def test_measure_is_the_quantile_the_rule_names(self):
        config = _downswing(2000.0)
        allocation = mix.evaluate((2, 2, 2), config)
        rule = tolerance.DownswingTolerance()
        self.assertAlmostEqual(
            rule.measure(allocation, config),
            sim.drawdown_quantile(
                config, allocation, hands=100_000, quantile=0.95,
                paths=sim.TOLERANCE_PATHS,
            ),
        )

    def test_a_huge_limit_admits_the_same_mix_the_ruin_rule_would(self):
        # With the constraint switched off in all but name, the objective alone
        # decides - and both rules maximise the same objective.
        loose = _downswing(10_000_000.0)
        allocations = mix.all_allocations(loose)
        best = mix.best_allocation(allocations, loose)
        self.assertEqual(
            best.eur_per_hour, max(a.eur_per_hour for a in allocations)
        )

    def test_tightening_the_limit_never_raises_the_answer(self):
        # Limits chosen around the real scale for this config: at 100k hands the
        # mixes here run p95 falls of roughly 1.6k (all 50NL) to 8.4k (all 200NL).
        earnings = []
        for amount in (2000.0, 3000.0, 5000.0, 8000.0, 12_000.0):
            config = _downswing(amount)
            best = mix.best_allocation(mix.all_allocations(config), config)
            self.assertIsNotNone(best, f"nothing admitted at a {amount:,.0f} limit")
            earnings.append(best.eur_per_hour)
        self.assertEqual(earnings, sorted(earnings))

    def test_the_chosen_mix_actually_satisfies_the_rule(self):
        # The walk short-circuits on the first acceptance, so this is the check
        # that it short-circuits on a REAL one.
        config = _downswing(5000.0)
        best = mix.best_allocation(mix.all_allocations(config), config)
        self.assertIsNotNone(best)
        rule = tolerance.for_config(config)
        self.assertTrue(rule.admits(best, config))
        self.assertLessEqual(rule.measure(best, config), config.downswing_amount_eur)

    def test_it_takes_the_most_it_can_afford(self):
        # Not merely "admissible" - the BEST admissible. Nothing the rule would
        # also admit may earn more than the mix chosen.
        config = _downswing(5000.0)
        allocations = mix.all_allocations(config)
        best = mix.best_allocation(allocations, config)
        rule = tolerance.for_config(config)
        for allocation in allocations:
            if allocation.eur_per_hour > best.eur_per_hour:
                self.assertFalse(
                    rule.admits(allocation, config),
                    f"{allocation.label} earns more and is also inside tolerance",
                )

    def test_nothing_admissible_returns_none(self):
        config = _downswing(1.0)
        self.assertIsNone(mix.best_allocation(mix.all_allocations(config), config))

    def test_the_mode_changes_the_answer(self):
        # If this ever passes trivially the two rules have collapsed into one and
        # the whole feature is decorative. At a 20% ruin tolerance every mix here
        # clears on ruin, so that rule takes the boldest; the downswing rule at
        # 4k does not.
        ruin_config = _config(ruin_tolerance=0.20)
        downswing_config = _downswing(4000.0, ruin_tolerance=0.20)
        self.assertNotEqual(
            mix.best_allocation(mix.all_allocations(ruin_config), ruin_config).counts,
            mix.best_allocation(
                mix.all_allocations(downswing_config), downswing_config
            ).counts,
        )


def _ladder(**overrides):
    """A wide ladder, so the bold end is big enough for the walk to get lost in."""
    settings = dict(
        bankroll_eur=40_000.0,
        tables=8,
        ruin_tolerance=0.0001,
        stakes=(
            Stake("50NL", 0.5, 7.0, 95.0),
            Stake("100NL", 1.0, 5.5, 92.0),
            Stake("200NL", 2.0, 4.5, 92.0),
            Stake("400NL", 4.0, 3.8, 92.0),
            Stake("1KNL", 10.0, 3.0, 92.0),
        ),
    )
    settings.update(overrides)
    return Config(**settings)


class TestTheWalkFindsWhatExists(unittest.TestCase):
    """Regression: the walk used to give up and report that nothing qualified.

    Sorted by earnings, the head of a wide ladder is all high-variance mixes that
    fail a downswing bar. With a fixed budget of simulations and no free way to
    reject them, the walk spent the lot before reaching anything admissible and
    returned None - which the CLI printed as "nothing clears your tolerance".
    That is a wrong answer, not a slow one: it sends you down a stake for no
    reason. The analytic floor is what fixed it.
    """

    def _config(self):
        return _ladder(
            risk_mode="downswing",
            downswing_amount_eur=9_000.0,
            downswing_hands=200_000,
            downswing_probability=0.05,
        )

    def test_it_agrees_with_an_exhaustive_scan(self):
        config = self._config()
        allocations = mix.all_allocations(config)
        rule = tolerance.for_config(config)

        # The answer by brute force: best-earning mix the rule admits, no budget,
        # no pruning, no ordering cleverness.
        admissible = [a for a in allocations if rule.admits(a, config)]
        self.assertTrue(admissible, "fixture is wrong - nothing is admissible")
        expected = max(admissible, key=lambda a: a.eur_per_hour)

        self.assertEqual(mix.best_allocation(allocations, config).counts, expected.counts)

    def test_the_search_reports_itself_complete(self):
        config = self._config()
        search = mix.search_allocations(mix.all_allocations(config), config)
        self.assertTrue(search.exhausted)
        self.assertIsNotNone(search.best)

    def test_the_free_prune_carries_most_of_the_work(self):
        config = self._config()
        search = mix.search_allocations(mix.all_allocations(config), config)
        self.assertGreater(search.pruned, search.tested)

    def test_a_budget_that_runs_out_is_not_reported_as_nothing_found(self):
        """The distinction the old code collapsed."""
        config = self._config()
        allocations = mix.all_allocations(config)
        original = mix.MAX_TOLERANCE_TESTS
        try:
            mix.MAX_TOLERANCE_TESTS = 1
            search = mix.search_allocations(allocations, config)
        finally:
            mix.MAX_TOLERANCE_TESTS = original
        if search.best is None:
            self.assertFalse(
                search.exhausted,
                "returned nothing AND claimed the search was complete",
            )


class TestTheAnalyticFloor(unittest.TestCase):
    def test_it_never_exceeds_the_simulated_figure(self):
        """Soundness. If the bound ever came out above the real number it would
        reject admissible mixes, and the walk would silently skip the answer."""
        config = _ladder(
            risk_mode="downswing",
            downswing_amount_eur=9_000.0,
            downswing_hands=200_000,
            downswing_probability=0.05,
        )
        rule = tolerance.DownswingTolerance()
        checked = 0
        for allocation in mix.all_allocations(config)[::17]:
            floor = rule.floor(allocation, config)
            if floor is None:
                continue
            self.assertLessEqual(floor, rule.measure(allocation, config) + 1e-9)
            checked += 1
        self.assertGreater(checked, 5)


class TestBothMode(unittest.TestCase):
    def _configs(self):
        common = dict(
            downswing_amount_eur=9_000.0,
            downswing_hands=200_000,
            downswing_probability=0.05,
        )
        return (
            _ladder(risk_mode="ruin", **common),
            _ladder(risk_mode="downswing", **common),
            _ladder(risk_mode="both", **common),
        )

    def test_it_is_the_intersection(self):
        ruin_config, down_config, both_config = self._configs()
        allocations = mix.all_allocations(both_config)
        both = tolerance.for_config(both_config)
        for allocation in allocations[::13]:
            self.assertEqual(
                both.admits(allocation, both_config),
                tolerance.RuinTolerance().admits(allocation, ruin_config)
                and tolerance.DownswingTolerance().admits(allocation, down_config),
            )

    def test_it_never_earns_more_than_either_rule_alone(self):
        ruin_config, down_config, both_config = self._configs()

        def solve(config):
            best = mix.best_allocation(mix.all_allocations(config), config)
            return best.eur_per_hour if best else 0.0

        both = solve(both_config)
        self.assertLessEqual(both, solve(ruin_config) + 1e-9)
        self.assertLessEqual(both, solve(down_config) + 1e-9)

    def test_it_matches_whichever_rule_is_stricter(self):
        ruin_config, down_config, both_config = self._configs()

        def solve(config):
            best = mix.best_allocation(mix.all_allocations(config), config)
            return best.eur_per_hour if best else 0.0

        self.assertAlmostEqual(
            solve(both_config), min(solve(ruin_config), solve(down_config))
        )

    def test_it_names_the_leg_that_bound(self):
        _, _, config = self._configs()
        rule = tolerance.for_config(config)
        best = mix.best_allocation(mix.all_allocations(config), config)
        self.assertIsNone(rule.binding(best, config))
        # And something bolder than the winner must be rejected by a NAMED leg.
        bolder = [
            a for a in mix.all_allocations(config)
            if a.eur_per_hour > best.eur_per_hour
        ]
        self.assertTrue(bolder)
        self.assertIn(rule.binding(bolder[0], config), ("ruin", "downswing"))

    def test_the_config_demands_both_sets_of_numbers(self):
        with self.assertRaises(ConfigError):
            _ladder(risk_mode="both")  # no downswing_amount

    def test_both_limits_are_drawn_on_both_charts(self):
        from shotopt import charts

        _, _, config = self._configs()
        for figure in (
            charts.allocation_frontier_figure(config),
            charts.allocation_frontier_downswing_figure(config),
        ):
            # Both bars are drawn identically and told apart by COLOUR, so that
            # is what has to be on the chart - one line in each limit colour.
            colours = {
                line.get_color() for line in figure.axes[0].get_lines()
                if line.get_linestyle() == "--"
            }
            self.assertEqual(
                colours, {charts.COL_RUIN_LIMIT, charts.COL_DOWNSWING_LIMIT},
                "expected a ruin bar and a downswing bar on every chart",
            )


class TestExposure(unittest.TestCase):
    """`On tables`: the money in front of you at once, at 100bb a seat."""

    def test_it_is_the_sum_of_the_buy_ins(self):
        config = _config()
        allocation = mix.evaluate((2, 3, 1), config)
        self.assertAlmostEqual(
            allocation.exposure_eur,
            2 * 100 * 0.5 + 3 * 100 * 1.0 + 1 * 100 * 2.0,
        )

    def test_one_stake_matches_the_screen_row(self):
        """The screen prices the whole table count at one stake, so a pure
        allocation and that stake's screen row must agree."""
        config = _config()
        for index, screen in enumerate(mix.screen_stakes(config)):
            counts = tuple(
                config.tables if i == index else 0 for i in range(len(config.stakes))
            )
            self.assertAlmostEqual(
                mix.evaluate(counts, config).exposure_eur, screen.exposure_eur
            )

    def test_it_rises_with_the_stakes_played(self):
        config = _config()
        low = mix.evaluate((config.tables, 0, 0), config)
        high = mix.evaluate((0, 0, config.tables), config)
        self.assertLess(low.exposure_eur, high.exposure_eur)

    def test_it_is_reported_in_the_display_currency(self):
        eur = _config()
        gbp = _config(currency=GBP)
        # Internally identical - the conversion happens only where it is printed.
        self.assertAlmostEqual(
            mix.evaluate((2, 2, 2), eur).exposure_eur,
            mix.evaluate((2, 2, 2), gbp).exposure_eur,
        )
        self.assertAlmostEqual(
            gbp.currency.from_eur(mix.evaluate((2, 2, 2), gbp).exposure_eur),
            mix.evaluate((2, 2, 2), eur).exposure_eur / 1.16,
        )


class TestOddsAgainst(unittest.TestCase):
    def test_readable_odds_are_spelled_out(self):
        from shotopt import ruin

        self.assertEqual(ruin.odds_against(1e-4), "10,000/1")
        self.assertEqual(ruin.odds_against(0.01), "100/1")
        self.assertEqual(ruin.odds_against(0.5), "2/1")

    def test_anything_rarer_than_a_million_to_one_is_one_band(self):
        """The safe end runs to 1e-129, where the literal odds are a 130-digit
        integer. No decision turns on which side of that you are."""
        from shotopt import ruin

        for probability in (1e-7, 1e-12, 1e-60, 1e-129):
            self.assertEqual(ruin.odds_against(probability), "<1M/1")

    def test_the_extremes_do_not_raise(self):
        from shotopt import ruin

        self.assertEqual(ruin.odds_against(0.0), "<1M/1")
        self.assertEqual(ruin.odds_against(1.0), "certain")


class TestSimulationAxisIsNetIncome(unittest.TestCase):
    def test_zero_is_the_start_and_ruin_is_below_it(self):
        from shotopt import charts, sim

        config = _config(currency=GBP, timescale_hands=200_000, sim_paths=400)
        allocation = mix.evaluate((2, 2, 2), config)
        result = sim.simulate(config, allocation, hands=200_000, paths=400)
        (low, high), _ = charts.simulation_scales([result], config, [allocation])

        # Room for the ruin barrier a whole bankroll below break-even.
        self.assertLess(low, -config.bankroll_eur)
        self.assertGreater(high, 0)

    def test_the_axis_is_labelled_as_net_income(self):
        from shotopt import charts, sim

        config = _config(currency=GBP, timescale_hands=200_000, sim_paths=400)
        allocation = mix.evaluate((2, 2, 2), config)
        result = sim.simulate(config, allocation, hands=200_000, paths=400)
        figure = charts.simulation_figure(result, config)
        self.assertIn("Net income", figure.axes[0].get_ylabel())
        text = " ".join(t.get_text() for t in figure.axes[0].texts)
        self.assertIn("ruin", text)
        self.assertNotIn("broke", text)


class TestCutPoint(unittest.TestCase):
    def test_a_single_crossing_lands_between_the_two_points(self):
        from shotopt import charts

        items = [1, 2, 3, 4, 5]
        cut = charts._cut_point(items, lambda i: i <= 3, lambda i: float(i))
        self.assertAlmostEqual(cut, 3.5)

    def test_no_line_when_the_rule_never_bites(self):
        from shotopt import charts

        self.assertIsNone(
            charts._cut_point([1, 2, 3], lambda i: True, lambda i: float(i))
        )

    def test_no_line_when_the_boundary_is_not_a_single_crossing(self):
        """Two flips means the admissible set is not one side of a line, so
        drawing one would claim a boundary that does not exist."""
        from shotopt import charts

        self.assertIsNone(
            charts._cut_point(
                [1, 2, 3, 4], lambda i: i in (1, 4), lambda i: float(i)
            )
        )


class TestWorkbook(unittest.TestCase):
    """The deck's data file.

    Read back through the xlsx's own XML: `xlsxwriter` is write-only and this
    repo has no reader dependency, but the sheet names and row counts live in
    the archive in plain text, which is enough to prove each tab exists and
    carries the rows it claims.
    """

    @classmethod
    def setUpClass(cls):
        import tempfile
        from pathlib import Path

        from shotopt import deck

        cls.config = _config(
            tables=5,
            risk_mode="both",
            downswing_amount_eur=15_000.0,
            downswing_hands=200_000,
            downswing_probability=0.10,
            currency=GBP,
            timescale_hands=200_000,
            sim_paths=500,
        )
        cls.path = Path(tempfile.mkdtemp()) / "data.xlsx"
        deck.build(cls.config, cls.path.parent, workbook_path=cls.path)

    def _sheet_xml(self):
        """Map of sheet name -> its XML, via the workbook's relationship ids."""
        import re
        import zipfile

        with zipfile.ZipFile(self.path) as archive:
            book = archive.read("xl/workbook.xml").decode("utf-8")
            names = re.findall(r'<sheet name="([^"]+)"', book)
            return {
                name: archive.read(f"xl/worksheets/sheet{index}.xml").decode("utf-8")
                for index, name in enumerate(names, start=1)
            }

    def test_every_declared_tab_is_written(self):
        from shotopt import workbook

        sheets = self._sheet_xml()
        for name, _ in workbook.SHEETS:
            self.assertIn(name, sheets)

    def test_allocations_holds_every_mix(self):
        import re

        from shotopt import mix as mix_module

        expected = len(mix_module.all_allocations(self.config))
        dimension = re.search(
            r'<dimension ref="A1:[A-Z]+(\d+)"', self._sheet_xml()["ALLOCATIONS"]
        )
        self.assertIsNotNone(dimension)
        # +1 for the header row.
        self.assertEqual(int(dimension.group(1)), expected + 1)

    def test_money_headers_carry_the_display_currency(self):
        sheets = self._sheet_xml()
        # Headers are shared strings, so check the workbook's string table.
        import zipfile

        with zipfile.ZipFile(self.path) as archive:
            strings = archive.read("xl/sharedStrings.xml").decode("utf-8")
        self.assertIn("per_hour_gbp", strings)
        self.assertNotIn("per_hour_eur", strings)
        self.assertIn("winrate_bb100", strings)  # bb columns are never converted
        self.assertTrue(sheets)

    def test_it_is_optional(self):
        """No path, no workbook - the deck must not require it."""
        import tempfile
        from pathlib import Path

        from shotopt import deck

        directory = Path(tempfile.mkdtemp())
        deck.build(self.config, directory)
        self.assertEqual(list(directory.glob("*.xlsx")), [])


class TestDrawdownCache(unittest.TestCase):
    def test_two_mixes_with_the_same_shape_share_an_answer(self):
        """The dedupe in `best_allocation` leans on this being EXACT.

        The simulation consumes only (mean, variance, bankroll, horizon), so two
        allocations agreeing on those must produce the same distribution - not
        approximately, identically, because the second is a cache hit.
        """
        config = _downswing(2000.0)
        first = mix.evaluate((3, 2, 1), config)
        # Same mean and variance, different counts: constructed by hand rather
        # than searched for, so the test does not depend on such a pair existing.
        twin = type(first)(
            counts=(1, 2, 3),
            stakes=first.stakes,
            mean_eur_per_100=first.mean_eur_per_100,
            variance_eur_per_100=first.variance_eur_per_100,
            eur_per_hour=first.eur_per_hour,
            risk_of_ruin=first.risk_of_ruin,
            within_ruin_tolerance=first.within_ruin_tolerance,
            drawdown_50=first.drawdown_50,
        )
        rule = tolerance.DownswingTolerance()
        self.assertEqual(rule.measure(first, config), rule.measure(twin, config))

    def test_the_bankroll_is_part_of_the_cache_key(self):
        """Two bankrolls must not share a cache entry, even when they agree.

        Ruin is absorbing, so in general the barrier position changes the
        drawdowns and the bankroll-ladder rows would be wrong if the key dropped
        it. The VALUES often coincide anyway (see the test below), so this checks
        the mechanism directly rather than inferring it from a difference that
        may not be there.
        """
        small = _downswing(2000.0, bankroll_eur=1500.0)
        large = _downswing(2000.0, bankroll_eur=50_000.0)
        sim._DRAWDOWN_CACHE.clear()
        rule = tolerance.DownswingTolerance()
        rule.measure(mix.evaluate((2, 2, 2), small), small)
        rule.measure(mix.evaluate((2, 2, 2), large), large)
        self.assertEqual(len(sim._DRAWDOWN_CACHE), 2)

    def test_a_short_horizon_makes_drawdowns_bankroll_independent(self):
        """Documents a real property of the simulator, so it is not mistaken for a bug.

        `sim.simulate` walks in chunks of 2,000 steps (200,000 hands) and only
        freezes a busted path from the NEXT chunk. Any horizon inside one chunk
        therefore has no absorption at all, and the worst peak-to-trough fall is
        the unconstrained one whatever the bankroll - a path can "fall" further
        than it had money to lose.

        That is the conservative direction (it over-states the downswing rather
        than under-stating it) and it matches how the deck already frames these
        figures: a fixed mix with no move-down rule, an upper bound rather than a
        forecast. Worth knowing when reading a downswing tolerance set on a
        horizon shorter than 200k hands.
        """
        tiny = _downswing(2000.0, bankroll_eur=300.0, downswing_hands=100_000)
        huge = _downswing(2000.0, bankroll_eur=500_000.0, downswing_hands=100_000)
        rule = tolerance.DownswingTolerance()
        self.assertEqual(
            rule.measure(mix.evaluate((2, 2, 2), tiny), tiny),
            rule.measure(mix.evaluate((2, 2, 2), huge), huge),
        )


if __name__ == "__main__":
    unittest.main()
