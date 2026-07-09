"""Unit tests for wc.data match helpers: has_result / final_score / penalty_winner.

These are pure functions over the openfootball score object, whose shape is:
    score = {"ht":[..], "ft":[g1,g2], "et":[g1,g2], "p":[p1,p2]}  (any key optional)
"""
import unittest

from wc import data


def m(team1="A", team2="B", **score):
    d = {"team1": team1, "team2": team2}
    if score:
        d["score"] = score
    return d


class HasResultTest(unittest.TestCase):
    def test_no_score_object(self):
        self.assertFalse(data.has_result(m()))

    def test_empty_score_object(self):
        self.assertFalse(data.has_result({"team1": "A", "team2": "B", "score": {}}))

    def test_ft_present(self):
        self.assertTrue(data.has_result(m(ft=[2, 1])))

    def test_goalless_draw_still_counts(self):
        # ft=[0,0] is a played result, not "no result".
        self.assertTrue(data.has_result(m(ft=[0, 0])))

    def test_halftime_only_is_not_a_result(self):
        self.assertFalse(data.has_result(m(ht=[1, 0])))


class FinalScoreTest(unittest.TestCase):
    def test_unplayed_returns_none(self):
        self.assertIsNone(data.final_score(m()))

    def test_full_time_only(self):
        self.assertEqual(data.final_score(m(ft=[2, 1])), (2, 1))

    def test_extra_time_supersedes_full_time(self):
        self.assertEqual(data.final_score(m(ft=[1, 1], et=[2, 1])), (2, 1))

    def test_full_time_used_when_no_extra_time(self):
        self.assertEqual(data.final_score(m(ft=[0, 3])), (0, 3))

    def test_penalties_do_not_change_final_score(self):
        # A shootout leaves the (level) ft/et score as the "final score"; the pens
        # only decide the winner, not the scoreline.
        self.assertEqual(data.final_score(m(ft=[1, 1], et=[1, 1], p=[4, 2])), (1, 1))


class PenaltyWinnerTest(unittest.TestCase):
    def test_no_penalties_returns_none(self):
        self.assertIsNone(data.penalty_winner(m(ft=[2, 1])))

    def test_team1_wins_shootout(self):
        self.assertEqual(
            data.penalty_winner(m("Brazil", "Chile", ft=[1, 1], p=[5, 4])), "Brazil")

    def test_team2_wins_shootout(self):
        self.assertEqual(
            data.penalty_winner(m("Brazil", "Chile", ft=[1, 1], p=[3, 5])), "Chile")


if __name__ == "__main__":
    unittest.main()
