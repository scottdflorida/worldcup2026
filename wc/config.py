"""Static configuration for the World Cup 2026 tracker."""

# Live, public-domain data source (no API key required). Auto-updated by the
# openfootball project from official FIFA results.
DATA_URL = "https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json"

# Local cache of the raw feed (committed so the site can build offline / when
# the source is briefly unreachable).
CACHE_PATH = "data/worldcup2026.json"
LAST_UPDATED_PATH = "data/last_updated.txt"

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

# Ordering of the knockout rounds for rendering the bracket left-to-right.
KO_ROUNDS = [
    "Round of 32",
    "Round of 16",
    "Quarter-final",
    "Semi-final",
    "Final",
]
