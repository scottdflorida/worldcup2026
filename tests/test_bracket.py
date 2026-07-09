"""Unit tests for wc.bracket slot-token resolution and match outcome helpers.

The openfootball feed names knockout participants with slot tokens; resolve_slot
turns them into concrete teams or candidate sets against the group standings and
the played matches:
    1C / 2C        group winner / runner-up
    3A/B/C/D       a third-placed team from one of those groups (candidate set)
    W76 / L101     winner / loser of match 76 / 101 (decided or recursive)
match_winner also folds in extra time and penalty shootouts.
"""
import unittest

from wc import bracket


def played(num, team1, team2, **score):
    return {"num": num, "team1": team1, "team2": team2, "score": score,
            "round": "Round of 32"}


class MatchWinnerLoserTest(unittest.TestCase):
    def test_unplayed_has_no_winner(self):
        self.assertIsNone(bracket.match_winner({"team1": "A", "team2": "B"}))
        self.assertIsNone(bracket.match_loser({"team1": "A", "team2": "B"}))

    def test_regulation_win(self):
        game = played(1, "Spain", "Japan", ft=[3, 1])
        self.assertEqual(bracket.match_winner(game), "Spain")
        self.assertEqual(bracket.match_loser(game), "Japan")

    def test_regulation_win_away(self):
        self.assertEqual(bracket.match_winner(played(1, "Spain", "Japan", ft=[0, 2])), "Japan")

    def test_extra_time_decides(self):
        # Level after 90, settled in ET -> ET score picks the winner.
        game = played(2, "France", "Ghana", ft=[1, 1], et=[2, 1])
        self.assertEqual(bracket.match_winner(game), "France")
        self.assertEqual(bracket.match_loser(game), "Ghana")

    def test_penalty_shootout_decides(self):
        game = played(3, "Italy", "Egypt", ft=[1, 1], p=[4, 2])
        self.assertEqual(bracket.match_winner(game), "Italy")
        self.assertEqual(bracket.match_loser(game), "Egypt")

    def test_level_with_no_penalties_is_unresolved(self):
        # Still level after ET and NO shootout recorded -> winner unknown (None),
        # not an arbitrary team.
        game = played(4, "Italy", "Egypt", ft=[1, 1], et=[2, 2])
        self.assertIsNone(bracket.match_winner(game))
        self.assertIsNone(bracket.match_loser(game))


class ResolveGroupSlotTest(unittest.TestCase):
    def _complete_group(self):
        # Group H finished: table order H1..H4.
        return {"Group H": {
            "table": [{"team": "H1"}, {"team": "H2"}, {"team": "H3"}, {"team": "H4"}],
            "complete": True,
            "status": {t: {"possible_ranks": [i + 1]}
                       for i, t in enumerate(("H1", "H2", "H3", "H4"))},
        }}

    def test_decided_winner(self):
        r = bracket.resolve_slot("1H", self._complete_group(), {})
        self.assertEqual(r["team"], "H1")
        self.assertTrue(r["decided"])
        self.assertEqual(r["candidates"], {"H1"})

    def test_decided_runner_up(self):
        r = bracket.resolve_slot("2H", self._complete_group(), {})
        self.assertEqual(r["team"], "H2")
        self.assertTrue(r["decided"])

    def _open_group(self):
        # Group F still open (valid letters are A-L): X and Y can top it, Z and Q
        # are stuck in the bottom two.
        return {"Group F": {
            "table": [{"team": "X"}, {"team": "Y"}, {"team": "Z"}, {"team": "Q"}],
            "complete": False,
            "status": {"X": {"possible_ranks": [1, 2]}, "Y": {"possible_ranks": [1, 2]},
                       "Z": {"possible_ranks": [3, 4]}, "Q": {"possible_ranks": [3, 4]}},
        }}

    def test_provisional_winner_candidates(self):
        r = bracket.resolve_slot("1F", self._open_group(), {})
        self.assertIsNone(r["team"])
        self.assertFalse(r["decided"])
        self.assertEqual(r["candidates"], {"X", "Y"})
        self.assertEqual(r["provisional"], "X")

    def test_provisional_third_place_candidates(self):
        r = bracket.resolve_slot("3F", self._open_group(), {})
        self.assertEqual(r["candidates"], {"Z", "Q"})


class ResolveThirdMultiTokenTest(unittest.TestCase):
    def test_multi_group_third_candidate_set(self):
        def grp(third):
            return {"table": [{"team": "x"}, {"team": "y"}, {"team": third}],
                    "complete": False, "status": {}}
        analyses = {"Group A": grp("A3"), "Group B": grp("B3"), "Group C": grp("C3")}
        r = bracket.resolve_slot("3A/B/C", analyses, {})
        self.assertIsNone(r["team"])
        self.assertFalse(r["decided"])
        self.assertEqual(r["candidates"], {"A3", "B3", "C3"})
        self.assertEqual(r["label"], "3rd A/B/C")


class ResolveWinLoseSlotTest(unittest.TestCase):
    def _by_num(self):
        return bracket.index_matches([
            played(97, "Ghana", "Kenya", ft=[2, 1]),
            played(98, "Peru", "Chile", ft=[0, 3]),
            {"num": 100, "team1": "W97", "team2": "W98", "round": "Round of 16"},
        ])

    def test_decided_winner_slot(self):
        r = bracket.resolve_slot("W97", {}, self._by_num())
        self.assertEqual(r["team"], "Ghana")
        self.assertTrue(r["decided"])
        self.assertEqual(r["candidates"], {"Ghana"})

    def test_decided_loser_slot(self):
        r = bracket.resolve_slot("L97", {}, self._by_num())
        self.assertEqual(r["team"], "Kenya")
        self.assertTrue(r["decided"])

    def test_undecided_winner_slot_unions_candidates(self):
        # W100 feeds off W97 and W98; before match 100 is played its occupant is
        # "whoever wins 97 or 98" -> the union of both decided winners.
        r = bracket.resolve_slot("W100", {}, self._by_num())
        self.assertIsNone(r["team"])
        self.assertFalse(r["decided"])
        self.assertEqual(r["candidates"], {"Ghana", "Chile"})
        self.assertEqual(r["label"], "Winner M100")

    def test_missing_source_match(self):
        r = bracket.resolve_slot("W555", {}, self._by_num())
        self.assertIsNone(r["team"])
        self.assertFalse(r["decided"])


class ResolveConcreteNameTest(unittest.TestCase):
    def test_plain_team_name_passes_through(self):
        r = bracket.resolve_slot("Brazil", {}, {})
        self.assertEqual(r["team"], "Brazil")
        self.assertTrue(r["decided"])
        self.assertEqual(r["candidates"], {"Brazil"})


if __name__ == "__main__":
    unittest.main()
