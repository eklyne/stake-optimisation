"""Tests for the CSV copies of the printed tables."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from shotopt import export, mix
from shotopt.config import Config, Stake


def _config(**overrides) -> Config:
    defaults = dict(
        bankroll_eur=20_000.0,
        tables=6,
        ruin_tolerance=0.01,
        stakes=(
            Stake("50NL", 0.5, 7.0, 95.0, hands=150_000),
            Stake("200NL", 2.0, 3.5, 90.0),
            Stake("600NL", 6.0, 1.0, 88.0),  # dominated by 200NL
        ),
    )
    defaults.update(overrides)
    return Config(**defaults)


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class TestStakeScreenCsv(unittest.TestCase):
    def setUp(self):
        self.config = _config()
        self.dir = Path(tempfile.mkdtemp())
        self.screens = mix.screen_stakes(self.config)
        self.path = export.write_stake_screen(self.screens, self.dir / "stake_screen.csv")
        self.rows = _read(self.path)

    def test_one_row_per_stake_including_the_excluded(self):
        self.assertEqual([r["stake"] for r in self.rows], ["50NL", "200NL", "600NL"])

    def test_records_why_a_stake_was_dropped(self):
        dropped = self.rows[2]
        self.assertEqual(dropped["kept"], "0")
        self.assertEqual(dropped["dominated_by"], "200NL")

    def test_kept_stakes_have_no_dominator(self):
        for row in self.rows[:2]:
            self.assertEqual(row["kept"], "1")
            self.assertEqual(row["dominated_by"], "")

    def test_missing_optional_fields_are_blank_not_zero(self):
        # 200NL has no `hands`; a 0 here would read as "measured over no hands"
        # rather than "not supplied".
        self.assertEqual(self.rows[1]["hands"], "")
        self.assertEqual(self.rows[0]["max_tables"], "")

    def test_numbers_match_the_screen(self):
        self.assertAlmostEqual(
            float(self.rows[0]["eur_per_hour"]), self.screens[0].eur_per_hour, places=3
        )
        self.assertAlmostEqual(
            float(self.rows[0]["mean_eur_per_100"]), self.screens[0].mean_eur_per_100, places=3
        )


class TestFrontierCsv(unittest.TestCase):
    def setUp(self):
        self.config = _config()
        self.dir = Path(tempfile.mkdtemp())
        allocations = mix.all_allocations(self.config)
        self.edge = mix.frontier(allocations)
        self.best = mix.best_allocation(allocations)
        self.path = export.write_frontier(
            self.edge, self.config, self.best, self.dir / "frontier.csv"
        )
        self.rows = _read(self.path)

    def test_one_row_per_frontier_point(self):
        self.assertEqual(len(self.rows), len(self.edge))

    def test_table_counts_get_their_own_columns(self):
        # A "10x 100NL + 2x 200NL" label is unusable as a spreadsheet dimension.
        for row in self.rows:
            counts = [int(row[f"tables_{s.name}"]) for s in self.config.stakes]
            self.assertEqual(sum(counts), self.config.tables)

    def test_the_excluded_stake_column_is_present_and_empty(self):
        # The column exists so the CSV shape does not change when the screen
        # verdict changes, but nothing is ever allocated to it.
        self.assertTrue(all(int(row["tables_600NL"]) == 0 for row in self.rows))

    def test_exactly_one_row_is_flagged_best(self):
        flagged = [r for r in self.rows if r["is_best"] == "1"]
        self.assertEqual(len(flagged), 1)
        self.assertEqual(flagged[0]["mix"], self.best.label)

    def test_full_precision_is_kept_for_the_risk_columns(self):
        # Rounding ruin to the 2dp the terminal shows would collapse every safe
        # mix to "0.00%" and make the column useless for sorting.
        self.assertAlmostEqual(
            float(self.rows[0]["risk_of_ruin"]), self.edge[0].risk_of_ruin, places=12
        )

    def test_rows_are_ordered_like_the_printed_table(self):
        earnings = [float(r["eur_per_hour"]) for r in self.rows]
        self.assertEqual(earnings, sorted(earnings))


class TestWriteTables(unittest.TestCase):
    def test_creates_the_directory_and_both_files(self):
        config = _config()
        target = Path(tempfile.mkdtemp()) / "nested" / "out"
        allocations = mix.all_allocations(config)
        written = export.write_tables(
            mix.screen_stakes(config),
            mix.frontier(allocations),
            config,
            mix.best_allocation(allocations),
            target,
        )
        self.assertEqual([p.name for p in written], ["stake_screen.csv", "frontier.csv"])
        self.assertTrue(all(p.is_file() for p in written))

    def test_survives_no_allocation_clearing_tolerance(self):
        config = _config(bankroll_eur=50.0, ruin_tolerance=1e-9)
        allocations = mix.all_allocations(config)
        self.assertIsNone(mix.best_allocation(allocations))
        written = export.write_tables(
            mix.screen_stakes(config),
            mix.frontier(allocations),
            config,
            None,
            Path(tempfile.mkdtemp()),
        )
        rows = _read(written[1])
        self.assertTrue(all(r["is_best"] == "0" for r in rows))


if __name__ == "__main__":
    unittest.main()
