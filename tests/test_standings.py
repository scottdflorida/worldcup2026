"""Unit tests for wc.standings: FIFA tiebreakers and the best-thirds ranking.

Two hand-built, fully-played groups exercise the ordering rules:
  Group H -- two teams dead level on (Pts, GD, GF); head-to-head must decide.
  Group G -- two teams level on points; goal difference decides, and must WIN
             even when the lower team won the head-to-head (GD ranks above H2H).
"""
import unittest

from wc import standings


def gm(team1, team2, g1, g2, group):
    return {"team1": team1, "team2": team2, "group": group,
            "score": {"ft": [g1, g2]}}


# Group H: Charlie & Delta on 6; Alpha & Bravo dead level on 3/-1/1, Alpha won H2H.
GROUP_H = [
    gm("Alpha", "Bravo", 1, 0, "Group H"),
    gm("Charlie", "Alpha", 1, 0, "Group H"),
    gm("Delta", "Alpha", 1, 0, "Group H"),
    gm("Bravo", "Charlie", 1, 0, "Group H"),
    gm("Delta", "Bravo", 1, 0, "Group H"),
    gm("Charlie", "Delta", 2, 0, "Group H"),
]

# Group G: Top runs the table; Mid2 (GD -2) edges Mid1 (GD -3) even though Mid1
# beat Mid2 head-to-head, because overall GD outranks the head-to-head rule.
GROUP_G = [
    gm("Top", "Mid1", 3, 0, "Group G"),
    gm("Top", "Mid2", 3, 0, "Group G"),
    gm("Top", "Bot", 3, 0, "Group G"),
    gm("Mid1", "Mid2", 1, 0, "Group G"),
    gm("Bot", "Mid1", 1, 0, "Group G"),
    gm("Mid2", "Bot", 2, 0, "Group G"),
]


def order(info):
    return [row["team"] for row in info["table"]]


class HeadToHeadTest(unittest.TestCase):
    def setUp(self):
        self.info = standings.analyze_group(GROUP_H)

    def test_full_ordering(self):
        self.assertEqual(order(self.info), ["Charlie", "Delta", "Alpha", "Bravo"])

    def test_tie_broken_by_head_to_head(self):
        tbl = order(self.info)
        # Alpha and Bravo are level on Pts/GD/GF; Alpha beat Bravo, so Alpha is higher.
        self.assertLess(tbl.index("Alpha"), tbl.index("Bravo"))

    def test_group_is_complete(self):
        self.assertTrue(self.info["complete"])
        self.assertEqual(self.info["remaining"], 0)
        self.assertEqual(self.info["scenarios"], 1)  # 3**0 remaining outcomes

    def test_winner_status_collapses_to_final_rank(self):
        st = self.info["status"]
        self.assertEqual(st["Charlie"]["possible_ranks"], [1])
        self.assertTrue(st["Charlie"]["won_group"])
        self.assertTrue(st["Delta"]["clinched_top2"])
        self.assertEqual(st["Alpha"]["possible_ranks"], [3])


class GoalDifferenceTest(unittest.TestCase):
    def setUp(self):
        self.info = standings.analyze_group(GROUP_G)

    def test_ordering_by_goal_difference(self):
        self.assertEqual(order(self.info), ["Top", "Mid2", "Mid1", "Bot"])

    def test_goal_difference_outranks_head_to_head(self):
        tbl = order(self.info)
        # Mid1 beat Mid2 head-to-head, but Mid2's better GD puts it above Mid1.
        self.assertLess(tbl.index("Mid2"), tbl.index("Mid1"))


class BestThirdsShapeTest(unittest.TestCase):
    def setUp(self):
        self.analyses = standings.all_groups(GROUP_G + GROUP_H)
        self.thirds = standings.best_thirds(self.analyses)

    def test_one_third_per_group(self):
        self.assertEqual(len(self.thirds), 2)
        self.assertEqual({t["group"] for t in self.thirds}, {"Group G", "Group H"})

    def test_ranked_and_seeded(self):
        # Alpha (3, -1) outranks Mid1 (3, -3); both inside the top-eight cut.
        self.assertEqual([t["team"] for t in self.thirds], ["Alpha", "Mid1"])
        self.assertEqual([t["seed"] for t in self.thirds], [1, 2])

    def test_qualifies_flag_within_top_eight(self):
        self.assertTrue(all(t["qualifies"] for t in self.thirds))

    def test_row_shape(self):
        row = self.thirds[0]
        for key in ("team", "group", "Pts", "GD", "GF", "seed", "qualifies"):
            self.assertIn(key, row)


if __name__ == "__main__":
    unittest.main()
