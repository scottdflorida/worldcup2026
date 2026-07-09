"""Unit tests for wc.util: URL slugs, page filenames, and deterministic accents.

Slugs must be ASCII, stable, and collision-safe across accented names and
punctuation (they become filenames and #hrefs). Accents must be identical every
build so team colours never shift between deploys.
"""
import unittest

from wc import util


class SlugTest(unittest.TestCase):
    def test_ampersand_becomes_and(self):
        self.assertEqual(util.slug("Bosnia & Herzegovina"), "bosnia-and-herzegovina")

    def test_cedilla_stripped(self):
        self.assertEqual(util.slug("Curaçao"), "curacao")

    def test_apostrophe_and_accents(self):
        self.assertEqual(util.slug("Côte d'Ivoire"), "cote-d-ivoire")

    def test_plain_name_lowercased(self):
        self.assertEqual(util.slug("Brazil"), "brazil")

    def test_leading_trailing_separators_trimmed(self):
        self.assertEqual(util.slug("  Korea Republic  "), "korea-republic")

    def test_empty_or_symbol_only_falls_back(self):
        self.assertEqual(util.slug("!!!"), "team")
        self.assertEqual(util.slug(""), "team")


class PageForTest(unittest.TestCase):
    def test_appends_html(self):
        self.assertEqual(util.page_for("Brazil"), "brazil.html")

    def test_uses_the_slug(self):
        self.assertEqual(util.page_for("Bosnia & Herzegovina"),
                         "bosnia-and-herzegovina.html")


class AccentTest(unittest.TestCase):
    def test_hand_picked_team_from_meta(self):
        self.assertEqual(util.accent("Brazil"), ("#009c3b", "#ffdf00"))
        self.assertEqual(util.accent("USA"), ("#0a3161", "#b31942"))

    def test_auto_accent_exact_formula(self):
        # h = (sum(ord) * 47) % 360; secondary hue = (h + 38) % 360.
        # "Wales" -> 508 * 47 = 23876 -> 116.
        self.assertEqual(util.accent("Wales"),
                         ("hsl(116,58%,42%)", "hsl(154,64%,52%)"))

    def test_auto_accent_is_stable(self):
        self.assertEqual(util.accent("Freedonia"), util.accent("Freedonia"))

    def test_auto_accent_shape(self):
        primary, secondary = util.accent("Freedonia")
        self.assertTrue(primary.startswith("hsl("))
        self.assertTrue(secondary.startswith("hsl("))


if __name__ == "__main__":
    unittest.main()
