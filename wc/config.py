"""Static configuration for the World Cup 2026 tracker."""
import os
from pathlib import Path

# Repo root + the data directory (where all cached feeds/blurbs/odds/squads
# live). WC_DATA_DIR lets tests point the whole data layer at a temp copy; unset,
# it resolves to <repo>/data, so a normal build is byte-identical.
# Contract: WC_DATA_DIR is read ONCE, at import — set it in the environment
# before the first `import wc.*` (as build.py and the golden harness's fresh
# subprocesses do); it cannot be changed mid-process.
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("WC_DATA_DIR", str(ROOT / "data")))

# Live, public-domain data source (no API key required). Auto-updated by the
# openfootball project from official FIFA results.
DATA_URL = "https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json"

# Local cache of the raw feed (committed so the site can build offline / when
# the source is briefly unreachable), plus the other cached data layers — all
# derived from DATA_DIR so a single env var relocates the whole data directory.
CACHE_PATH        = str(DATA_DIR / "worldcup2026.json")
LAST_UPDATED_PATH = str(DATA_DIR / "last_updated.txt")
BLURBS_PATH       = str(DATA_DIR / "blurbs.json")
BLURBS_PT_PATH    = str(DATA_DIR / "blurbs.pt.json")
ODDS_PATH         = str(DATA_DIR / "odds.json")
SQUADS_PATH       = str(DATA_DIR / "squads.json")

# The site is team-agnostic: every nation gets its own hub page and any visitor
# can pin whichever teams they want to follow. This list is only the *default*
# watchlist shown on a first visit (before the visitor picks their own); it is
# stored client-side and fully overridable in the browser.
DEFAULT_WATCH = ["USA", "Brazil"]

# Per-team display + accent metadata used by the renderer. Optional — any team
# not listed here gets a deterministic auto-generated accent (see wc/util.py).
TEAM_META = {
    "Brazil": {"flag": "\U0001F1E7\U0001F1F7", "accent": "#009c3b", "accent2": "#ffdf00"},
    "USA": {"flag": "\U0001F1FA\U0001F1F8", "accent": "#0a3161", "accent2": "#b31942"},
}

TOURNAMENT = {
    "name": "FIFA World Cup 2026",
    "hosts": "United States · Canada · Mexico",
    "start": "2026-06-11",
    "final_date": "2026-07-19",
    "final_venue": "MetLife Stadium, New York/New Jersey",
    "teams": 48,
    "groups": 12,
}

# Ordering of the knockout rounds for rendering the bracket left-to-right. This
# is the main spine everything keys off (fantasy/betting filters, the bracket
# rail, forward/tree ordering).
KO_ROUNDS = [
    "Round of 32",
    "Round of 16",
    "Quarter-final",
    "Semi-final",
    "Final",
]

# Every knockout round in bracket order, including the third-place match (which
# sits just before the Final). Only build_bracket walks this wider list.
KO_ROUNDS_ALL = [
    "Round of 32",
    "Round of 16",
    "Quarter-final",
    "Semi-final",
    "Match for third place",
    "Final",
]

# Canonical short label per round. _round_short() overrides only "Final" (-> the
# full word); the bracket rail, fantasy and betting use these abbreviations as-is.
KO_SHORT = {
    "Round of 32": "R32",
    "Round of 16": "R16",
    "Quarter-final": "QF",
    "Semi-final": "SF",
    "Final": "F",
}
