"""Small helpers shared by the renderer: URL slugs and per-team accent colors."""
from __future__ import annotations

import re
import unicodedata

from . import config


def slug(team: str) -> str:
    s = unicodedata.normalize("NFKD", team).encode("ascii", "ignore").decode()
    s = s.lower().replace("&", "and")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "team"


def page_for(team: str) -> str:
    return f"{slug(team)}.html"


def accent(team: str):
    """Return a (primary, secondary) color pair for a team.

    Hand-picked teams come from config.TEAM_META; everyone else gets a stable,
    deterministic hue derived from the name so colors don't shift between builds.
    """
    meta = config.TEAM_META.get(team)
    if meta:
        return meta["accent"], meta["accent2"]
    h = (sum(ord(c) for c in team) * 47) % 360
    return f"hsl({h},58%,42%)", f"hsl({(h + 38) % 360},64%,52%)"
