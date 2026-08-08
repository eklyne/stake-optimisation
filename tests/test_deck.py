"""Smoke tests for the deck build.

Deliberately structural rather than visual: that the deck builds, has the six
slides in order, and that the numbers on the slides come from the same functions
the terminal prints. Nothing here can tell you a chart is ugly.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from shotopt import mix
from shotopt.config import Config, Stake

try:
    from pptx import Presentation

    from shotopt import deck

    AVAILABLE = True
except ImportError:  # python-pptx / matplotlib are optional for the text commands
    AVAILABLE = False


def _config(**overrides) -> Config:
    defaults = dict(
        bankroll_eur=5000.0,
        tables=6,
        ruin_tolerance=0.01,
        rakeback_pct=0.30,
        timescale_hands=200_000,
        sim_paths=800,
        stakes=(
            Stake("50NL", 0.5, 8.18, 92.0, hands=271_592, rake_bb100=10.195,
                  current_hands=23_082),
            Stake("100NL", 1.0, 7.46, 92.0, hands=79_329, rake_bb100=8.329,
                  current_hands=11_052),
            Stake("200NL", 2.0, 4.32, 92.0, hands=38_970, rake_bb100=6.545,
                  current_hands=13_760),
            Stake("600NL", 6.0, 67.73, 92.0, hands=1_043, rake_bb100=3.857,
                  max_tables=0, current_hands=600),
        ),
    )
    defaults.update(overrides)
    return Config(**defaults)


@unittest.skipUnless(AVAILABLE, "python-pptx not installed")
class TestDeck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = _config()
        cls.dir = Path(tempfile.mkdtemp())
        cls.path = deck.build(cls.config, cls.dir)
        cls.prs = Presentation(cls.path)

    def test_it_builds(self):
        self.assertTrue(self.path.is_file())
        self.assertGreater(self.path.stat().st_size, 10_000)

    def _slide(self, fragment):
        """Find a slide by a fragment of its title - indices move as the deck
        grows, and a test that breaks on reordering tests the wrong thing."""
        for slide in self.prs.slides:
            title = slide.shapes.title
            if title is not None and fragment in title.text:
                return slide
        raise AssertionError(f"no slide titled like {fragment!r}")

    def test_content_slides_in_order(self):
        titles = [
            s.shapes.title.text
            for s in self.prs.slides
            if s.shapes.title is not None and s.shapes.title.text
        ]
        expected = ["priced on its own", "big blinds", "euros", "one stake and nothing else",
                    "split the tables", "nearest alternatives", "optimal mix, simulated",
                    "two ways up", "bankroll grows", "actually playing",
                    "actually played, simulated", "Appendix"]
        self.assertEqual(len(titles), len(expected))
        for want, got in zip(expected, titles):
            self.assertIn(want, got)

    def test_four_section_dividers(self):
        # Chapter slides use a layout with no title placeholder, so they show up
        # as the untitled slides. Four sections, four dividers.
        untitled = [
            s for s in self.prs.slides
            if s.shapes.title is None or not s.shapes.title.text
        ]
        self.assertEqual(len(untitled), 4)

    def test_the_stake_table_lists_every_stake_including_excluded(self):
        table = next(s.table for s in self._slide("priced on its own").shapes if s.has_table)
        names = [table.cell(r, 0).text for r in range(1, len(table.rows))]
        self.assertEqual(names, [s.name for s in self.config.stakes])

    def test_the_excluded_stake_is_marked_as_such_on_the_slide(self):
        table = next(s.table for s in self._slide("priced on its own").shapes if s.has_table)
        verdicts = {
            table.cell(r, 0).text: table.cell(r, len(table.columns) - 1).text
            for r in range(1, len(table.rows))
        }
        self.assertEqual(verdicts["50NL"], "in the mix")
        self.assertIn("max_tables", verdicts["600NL"])

    def test_the_configuration_table_centres_on_the_chosen_mix(self):
        table = next(
            s.table for s in self._slide("nearest alternatives").shapes if s.has_table
        )
        last = len(table.columns) - 1  # the note column, wherever it has ended up
        notes = [table.cell(r, last).text for r in range(1, len(table.rows))]
        self.assertEqual(sum("CHOSEN" in n for n in notes), 1)

        best = mix.best_allocation(mix.all_allocations(self.config))
        labels = [table.cell(r, 0).text for r in range(1, len(table.rows))]
        self.assertIn(best.label, labels)

    def test_the_current_slide_shows_the_played_mix_against_the_optimum(self):
        table = next(s.table for s in self._slide("actually playing").shapes if s.has_table)
        labels = [table.cell(r, 1).text for r in range(1, len(table.rows))]
        best = mix.best_allocation(mix.all_allocations(self.config))
        self.assertIn(best.label, labels)
        self.assertIn(mix.current_allocation(self.config).label, labels)

    def test_the_waterfall_reconciles_to_the_screen(self):
        # before rake - rake + rakeback must equal what the screen calls banked,
        # or the slide is telling a different story from the terminal.
        for screen in mix.screen_stakes(self.config):
            if not screen.kept:
                continue
            stake = screen.stake
            before = stake.winrate_bb100 + stake.rake_bb100
            banked = before - stake.rake_bb100 + stake.rake_bb100 * self.config.rakeback_pct
            self.assertAlmostEqual(banked, screen.mean_eur_per_100 / stake.bb_eur, places=9)

    def test_it_builds_with_no_stake_inside_tolerance(self):
        # No chosen mix means nothing to step up FROM, nothing to simulate and
        # nothing to compare the current split against, so sections 2 and 3 drop
        # out rather than inventing a subject.
        config = _config(bankroll_eur=100.0, ruin_tolerance=1e-9)
        self.assertIsNone(mix.best_allocation(mix.all_allocations(config)))
        prs = Presentation(deck.build(config, Path(tempfile.mkdtemp())))
        titles = [s.shapes.title.text for s in prs.slides if s.shapes.title is not None]
        self.assertFalse(any("actually playing" in t for t in titles))

    def test_it_builds_without_a_current_distribution(self):
        # current_hands is optional; section 3 simply does not appear.
        stakes = tuple(
            Stake(s.name, s.bb_eur, s.winrate_bb100, s.stdev_bb100, s.hands,
                  s.max_tables, s.rake_bb100)
            for s in _config().stakes
        )
        config = _config(stakes=stakes)
        self.assertIsNone(mix.current_allocation(config))
        prs = Presentation(deck.build(config, Path(tempfile.mkdtemp())))
        titles = [
            s.shapes.title.text for s in prs.slides
            if s.shapes.title is not None and s.shapes.title.text
        ]
        self.assertFalse(any("actually play" in t for t in titles))


if __name__ == "__main__":
    unittest.main()
