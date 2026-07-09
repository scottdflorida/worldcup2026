"""Frontend assets (CSS / JS / SVG artwork) + the cache-busting fingerprint.

The CSS/JS/SVG live as real files under wc/assets/ (single source of truth) and
are loaded here at import so the module-level names below (STYLE, APP_JS,
BALL_SVG, …) stay unchanged for downstream code. Per the build contract they are
static — never hand-edit them to embed per-render data; cache-busting is handled
by _asset_ver(). render_site() resets _asset_ver_cache at the top of each render.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from . import i18n

_ASSETS = Path(__file__).resolve().parent / "assets"


# --------------------------------------------------------------------------
# Original, license-free SVG graphics (no FIFA/World Cup trademarks used)
# --------------------------------------------------------------------------
# Extracted to wc/assets/*.svg (single source of truth, loaded at import). All
# four are original ink-line art on the broadcast-ink palette — no FIFA/World
# Cup trademarks:
#   ball.svg    — ink-line ball on paper
#   trophy.svg  — flat ink cup with a single vermilion star
#   favicon.svg — mono "26" lockup (ink tile, vermilion numerals, hard edge)
#   og.svg      — 1200x630 broadsheet "Broadcast Ink" share card; regenerate
#                 og.png / apple-touch-icon.png from it (see scripts/og_png.md)
BALL_SVG = (_ASSETS / "ball.svg").read_text(encoding="utf-8")
TROPHY_SVG = (_ASSETS / "trophy.svg").read_text(encoding="utf-8")
FAVICON_SVG = (_ASSETS / "favicon.svg").read_text(encoding="utf-8")
OG_SVG = (_ASSETS / "og.svg").read_text(encoding="utf-8")


APP_JS = (_ASSETS / "app.js").read_text(encoding="utf-8")

STYLE = (_ASSETS / "style.css").read_text(encoding="utf-8")

# Cache-busting fingerprint for the CSS/JS/i18n assets. The HTML links them as
# style.css?v=<ver> / app.js?v=<ver> / i18n.js?v=<ver>; when any asset changes
# the version changes, so returning visitors fetch the new file instead of a
# stale cached one. Referenced by shell().
#
# Computed at RENDER time (not import), from the exact bytes write_site emits,
# and memoized for the duration of one render_site() call (reset at its top).
# The formula and inputs are unchanged, so the value is identical for a given
# build — but deferring to render time fixes a staleness bug: update.py imports
# render *before* refreshing blurbs, so an import-time hash reflected the
# PREVIOUS run's i18n.js (blurbs feed _asset_ver via i18n.build_js()).
_asset_ver_cache = None


def _asset_ver():
    global _asset_ver_cache
    if _asset_ver_cache is None:
        _asset_ver_cache = hashlib.sha256(
            (STYLE + APP_JS + i18n.build_js()).encode("utf-8")).hexdigest()[:10]
    return _asset_ver_cache
