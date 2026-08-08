"""Tests for config validation and the assembled per-stake report."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from shotopt.analysis import best_affordable, build_reports
from shotopt.config import Config, ConfigError, Stake, load_config

BASE_TOML = """
bankroll_eur = 5000
tables = 12
ruin_tolerance = 0.01

[[stake]]
name = "100NL"
bb_eur = 1.0
winrate_bb100 = 5.0
stdev_bb100 = 90.0
hands = 100000
"""


def _write(text: str) -> Path:
    handle = tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False, encoding="utf-8")
    handle.write(text)
    handle.close()
    return Path(handle.name)


def _config(**overrides) -> Config:
    defaults = dict(
        bankroll_eur=5000.0,
        tables=12,
        ruin_tolerance=0.01,
        stakes=(
            Stake("50NL", 0.5, 7.0, 95.0, 150_000),
            Stake("200NL", 2.0, 3.5, 90.0, 90_000),
        ),
    )
    defaults.update(overrides)
    return Config(**defaults)


class TestConfigLoading(unittest.TestCase):
    def test_loads_a_minimal_config(self):
        config = load_config(_write(BASE_TOML))
        self.assertEqual(config.bankroll_eur, 5000)
        self.assertEqual(config.tables, 12)
        self.assertEqual(config.kelly_fraction, 0.5)  # default
        self.assertEqual(config.stakes[0].name, "100NL")
        self.assertEqual(config.stakes[0].hands, 100_000)

    def test_hands_is_optional(self):
        config = load_config(_write(BASE_TOML.replace("hands = 100000", "")))
        self.assertIsNone(config.stakes[0].hands)

    def test_missing_file(self):
        with self.assertRaises(ConfigError):
            load_config(Path("no-such-config.toml"))

    def test_rejects_no_stakes(self):
        with self.assertRaises(ConfigError):
            load_config(_write("bankroll_eur = 1\ntables = 1\nruin_tolerance = 0.01\n"))

    def test_rejects_a_typo_rather_than_ignoring_it(self):
        # The failure mode this guards against: `stdev_bb_100` silently ignored,
        # the required key reported missing, and the user hunting a live typo.
        with self.assertRaises(ConfigError):
            load_config(_write(BASE_TOML + '\n[[stake]]\nname = "x"\nbb_eur = 1\n'
                               'winrate_bb100 = 1\nstdev_bb100 = 90\nhandz = 10\n'))
        with self.assertRaises(ConfigError):
            load_config(_write("bankrol_eur = 1\n" + BASE_TOML))

    def test_rejects_duplicate_stake_names(self):
        with self.assertRaises(ConfigError):
            load_config(_write(BASE_TOML + BASE_TOML.split("bankroll_eur = 5000")[-1]))

    def test_rejects_a_ruin_tolerance_given_as_a_percentage(self):
        # `ruin_tolerance = 5` meaning "5%" would otherwise pass every stake.
        with self.assertRaises(ConfigError):
            load_config(_write(BASE_TOML.replace("ruin_tolerance = 0.01", "ruin_tolerance = 5")))

    def test_rejects_a_negative_standard_deviation(self):
        with self.assertRaises(ConfigError):
            load_config(_write(BASE_TOML.replace("stdev_bb100 = 90.0", "stdev_bb100 = -90.0")))


class TestOverrides(unittest.TestCase):
    def test_replace_applies_only_non_none_values(self):
        config = _config()
        updated = config.replace(bankroll_eur=20_000.0, tables=None)
        self.assertEqual(updated.bankroll_eur, 20_000.0)
        self.assertEqual(updated.tables, 12)

    def test_replace_still_validates(self):
        with self.assertRaises(ConfigError):
            _config().replace(bankroll_eur=-1.0)


class TestReports(unittest.TestCase):
    def test_sorted_by_stake_size(self):
        reports = build_reports(_config())
        self.assertEqual([r.stake.name for r in reports], ["50NL", "200NL"])

    def test_a_bigger_bankroll_never_raises_risk(self):
        small = build_reports(_config(bankroll_eur=2000.0))
        large = build_reports(_config(bankroll_eur=50_000.0))
        for a, b in zip(small, large):
            self.assertGreaterEqual(a.risk_of_ruin, b.risk_of_ruin)

    def test_tolerance_verdict_tracks_the_tolerance(self):
        strict = build_reports(_config(ruin_tolerance=0.0001))
        loose = build_reports(_config(ruin_tolerance=0.5))
        self.assertLessEqual(
            sum(r.within_tolerance for r in strict), sum(r.within_tolerance for r in loose)
        )

    def test_the_affordable_set_grows_monotonically_with_the_bankroll(self):
        counts = [
            sum(r.within_tolerance for r in build_reports(_config(bankroll_eur=roll)))
            for roll in (1000.0, 5000.0, 20_000.0, 100_000.0)
        ]
        self.assertEqual(counts, sorted(counts))

    def test_best_affordable_picks_the_top_earner_inside_tolerance(self):
        reports = build_reports(_config(bankroll_eur=100_000.0))
        best = best_affordable(reports)
        self.assertIsNotNone(best)
        self.assertEqual(best.stake.name, "200NL")  # more EUR/hr, and now affordable

    def test_best_affordable_is_none_when_nothing_clears(self):
        reports = build_reports(_config(bankroll_eur=100.0, ruin_tolerance=1e-6))
        self.assertIsNone(best_affordable(reports))

    def test_a_losing_stake_leaves_the_derived_columns_empty(self):
        config = _config(stakes=(Stake("400NL", 4.0, -2.0, 90.0, 10_000),))
        report = build_reports(config)[0]
        self.assertEqual(report.risk_of_ruin, 1.0)
        self.assertFalse(report.within_tolerance)
        self.assertIsNone(report.bankroll_for_tolerance_eur)
        self.assertIsNone(report.kelly_bankroll_eur)

    def test_haircut_reduces_the_win_rate_and_the_hourly(self):
        plain = build_reports(_config())[0]
        cut = build_reports(_config(winrate_haircut_bb_per_table=0.1))[0]
        self.assertLess(cut.winrate_eff, plain.winrate_eff)
        self.assertLess(cut.eur_per_hour, plain.eur_per_hour)

    def test_correlation_raises_the_required_bankroll(self):
        plain = build_reports(_config())[0]
        correlated = build_reports(_config(table_correlation=0.15))[0]
        self.assertGreater(
            correlated.bankroll_for_tolerance_eur, plain.bankroll_for_tolerance_eur
        )

    def test_shaded_sizing_demands_more_than_the_point_estimate(self):
        report = build_reports(_config())[0]
        self.assertLess(report.shaded_winrate, report.winrate_eff)
        self.assertGreater(report.shaded_kelly_bankroll_eur, report.kelly_bankroll_eur)

    def test_no_hands_means_no_interval(self):
        config = _config(stakes=(Stake("100NL", 1.0, 5.0, 90.0, None),))
        report = build_reports(config)[0]
        self.assertIsNone(report.winrate_ci)
        self.assertIsNone(report.shaded_winrate)


if __name__ == "__main__":
    unittest.main()
