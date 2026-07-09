"""Small helpers shared by the renderer: URL slugs and per-team accent colors."""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime

from . import config


def fmt_date(d: str) -> str:
    """'2026-06-19' -> 'Friday, June 19'."""
    try:
        dt = datetime.strptime(d, "%Y-%m-%d")
    except (ValueError, TypeError):
        return d or ""
    return f"{dt.strftime('%A, %B')} {dt.day}"


def fmt_date_short(d: str) -> str:
    """'2026-06-28' -> 'Jun 28' (for tight spaces like the bracket)."""
    try:
        dt = datetime.strptime(d, "%Y-%m-%d")
    except (ValueError, TypeError):
        return d or ""
    return f"{dt.strftime('%b')} {dt.day}"


def ordinal(n) -> str:
    """1 -> '1st', 2 -> '2nd', 3 -> '3rd', 4 -> '4th', anything else -> '<n>th'."""
    return {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}.get(n, f"{n}th")


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


def _parse_color(c: str):
    """'#0a3161' or 'hsl(210,58%,42%)' -> (r, g, b) in 0..1."""
    c = c.strip()
    if c.startswith("#"):
        h = c[1:]
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    m = re.match(r"hsl\((\d+(?:\.\d+)?),\s*(\d+(?:\.\d+)?)%,\s*(\d+(?:\.\d+)?)%\)", c)
    if m:
        import colorsys
        hh, ss, ll = (float(m.group(i)) for i in (1, 2, 3))
        return colorsys.hls_to_rgb(hh / 360, ll / 100, ss / 100)
    return (0.5, 0.5, 0.5)


def _rel_lum(rgb) -> float:
    def f(ch):
        return ch / 12.92 if ch <= 0.03928 else ((ch + 0.055) / 1.055) ** 2.4
    r, g, b = (f(ch) for ch in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


# The team hero is an ink block in BOTH themes; near-black team colors (USA navy,
# etc.) vanish against it. Reference luminance of the darkest hero ground:
_INK_BLOCK_LUM = 0.012


def hero_accent(primary: str):
    """A contrast-safe version of a team's accent for use ON the ink-block hero.

    Blends the raw accent toward white until it clears 3:1 against the hero
    ground (WCAG large-object threshold), and picks a readable text color for
    fills using it. Returns (css_rgb, on_color). Deterministic, pure.
    """
    rgb = list(_parse_color(primary))
    for _ in range(12):
        lum = _rel_lum(rgb)
        if (lum + 0.05) / (_INK_BLOCK_LUM + 0.05) >= 3.0:
            break
        rgb = [ch + (1 - ch) * 0.14 for ch in rgb]   # 14% step toward white
    css = "rgb({},{},{})".format(*(round(ch * 255) for ch in rgb))
    on = "#171512" if _rel_lum(rgb) >= 0.35 else "#F4F2EC"
    return css, on
