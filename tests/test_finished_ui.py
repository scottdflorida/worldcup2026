"""Finished-tournament regressions for the home and watchlist summaries."""
from __future__ import annotations

import unittest

from wc.components import _card_status, bracket_rail
from wc.pages.home import _hero_progress


def _resolved(team):
    return {"team": team, "decided": True, "label": team,
            "candidates": {team}, "slot": team}


class _StatusContext:
    def __init__(self, matches, *, group_out=False, recent=None):
        self.matches = matches
        self._group_out = group_out
        self._recent = recent

    def next_match(self, _team):
        return None

    def knocked_out(self, _team):
        return self._group_out

    def team_fixtures(self, _team):
        return None, self._recent


class FinishedCardStatusTest(unittest.TestCase):
    def test_final_and_third_place_placements(self):
        matches = [
            {"round": "Match for third place", "team1": "France", "team2": "England",
             "score": {"ft": [4, 6]}},
            {"round": "Final", "team1": "Spain", "team2": "Argentina",
             "score": {"ft": [0, 0], "et": [1, 0]}},
        ]
        ctx = _StatusContext(matches)
        expected = {
            "Spain": ("<span>World champions</span>", "champ"),
            "Argentina": ("<span>Runners-up</span>", "out"),
            "England": ("<span>Third place</span>", "placed"),
            "France": ("<span>Fourth place</span>", "placed"),
        }
        for team, status in expected.items():
            with self.subTest(team=team):
                self.assertEqual(_card_status(ctx, team), status)

    def test_knockout_exit_names_the_round(self):
        recent = {"round": "Round of 16", "team1": "Brazil", "team2": "Norway",
                  "score": {"ft": [1, 2]}}
        ctx = _StatusContext([recent], recent=recent)
        self.assertEqual(_card_status(ctx, "Brazil"),
                         ("<span>Out in R16</span>", "out"))

    def test_group_exit_names_the_group_stage(self):
        ctx = _StatusContext([], group_out=True)
        self.assertEqual(_card_status(ctx, "Curaçao"),
                         ("<span>Out in group stage</span>", "out"))


class FinishedHomeTest(unittest.TestCase):
    def setUp(self):
        self.final_match = {
            "round": "Final", "team1": "Spain", "team2": "Argentina",
            "score": {"ft": [0, 0], "et": [1, 0]},
        }
        self.bronze_match = {
            "round": "Match for third place", "team1": "France", "team2": "England",
            "score": {"ft": [4, 6]},
        }
        self.ctx = type("Ctx", (), {})()
        self.ctx.matches = [self.bronze_match, self.final_match]
        self.ctx.bracket = [
            ("Match for third place", [{
                "team1": _resolved("France"), "team2": _resolved("England"),
                "score": {"ft": [4, 6]}, "played": True, "winner": "England",
            }]),
            ("Final", [{
                "team1": _resolved("Spain"), "team2": _resolved("Argentina"),
                "score": {"ft": [0, 0], "et": [1, 0]}, "played": True,
                "winner": "Spain",
            }]),
        ]

    def test_completed_bracket_keeps_each_medal_with_its_result(self):
        html = bracket_rail(self.ctx, "Final")
        self.assertIn('class="ko-rail krl-complete"', html)
        final_start = html.index("krl-title-col")
        bronze_start = html.index("krl-bronze-col")
        final_block = html[final_start:bronze_start]
        bronze_block = html[bronze_start:]
        for text in ("World Champion", "Spain", "Argentina", "Final result"):
            self.assertIn(text, final_block)
        for text in ("Bronze", "England", "France", "Third-place result"):
            self.assertIn(text, bronze_block)
        self.assertNotIn("Bronze", final_block)

    def test_complete_progress_has_no_end_tick(self):
        html = _hero_progress(self.ctx)
        self.assertIn('data-pct="100.00"', html)
        self.assertNotIn("tally-tick", html)


if __name__ == "__main__":
    unittest.main()
