"""Page chrome: the primary NAV, head/OpenGraph meta, the shell() wrapper
(header, footer, timezone picker) and the versioned asset tags.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from . import config, i18n
from .art import _asset_ver
from .times import E, PT_LABEL, PT_OFFSET_HOURS

SITE_URL = "https://worldcup.sflorida.studio"


NAV = [
    ("index.html", "Home"),
    ("teams.html", "Teams"),
    ("bracket.html", "Bracket"),
    ("fantasy.html", "Fantasy"),
    ("betting.html", "Bets"),
    ("calendar.html", "Calendar"),
]

# Social-share card. Must be a raster format — Discord/X/iMessage/Slack/Facebook
# do not render SVG previews (they fall back to a blank placeholder). og.png is a
# 1200x630 rasterization of OG_SVG, committed as a static asset (the build never
# rewrites it; only *.html is cleared). Regenerate it from OG_SVG if the card art
# changes (see scripts/og_png.md).
OG_IMG = "assets/og.png"
FAVICON = "assets/favicon.svg"
# iOS home-screen icon must be a PNG (it ignores SVG). 180x180 rasterization of
# FAVICON_SVG, committed as a static asset; see scripts/og_png.md for regen.
APPLE_ICON = "assets/apple-touch-icon.png"


def head_meta(title, desc, page):
    url = f"{SITE_URL}/{page}"
    img = f"{SITE_URL}/{OG_IMG}"
    return f"""<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{E(title)}</title>
<meta name="description" content="{E(desc)}">
<meta name="theme-color" content="#F4F2EC">
<link rel="icon" type="image/svg+xml" href="{FAVICON}">
<link rel="apple-touch-icon" sizes="180x180" href="{APPLE_ICON}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="World Cup 2026 Tracker">
<meta property="og:title" content="{E(title)}">
<meta property="og:description" content="{E(desc)}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{img}">
<meta property="og:image:secure_url" content="{img}">
<meta property="og:image:type" content="image/png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="World Cup 2026 Tracker — the World Cup is live">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{E(title)}">
<meta name="twitter:description" content="{E(desc)}">
<meta name="twitter:image" content="{img}">
<meta name="twitter:image:alt" content="World Cup 2026 Tracker — the World Cup is live">"""


def shell(title, active, body, ctx, desc=None, page="index.html"):
    desc = desc or ("Live FIFA World Cup 2026 tracker — groups, standings, advance "
                    "odds, team road-to-the-final and a connected knockout bracket. "
                    "Pin your teams with ★.")
    nav_items = []
    for href, label in NAV:
        on = href == active
        cur = ' aria-current="page"' if on else ''
        nav_items.append(
            f'<a class="{"on" if on else ""}" href="{href}"{cur}>{E(label)}</a>'
        )
    nav = "".join(nav_items)
    updated = ""
    upd_attr = ""
    if ctx.last_updated:
        try:
            dt = datetime.fromisoformat(ctx.last_updated).astimezone(timezone.utc)
            # Server fallback is Pacific (the default zone); data-utc lets the
            # client re-render it in the viewer's chosen zone, like every kickoff.
            pt = dt + timedelta(hours=PT_OFFSET_HOURS)
            updated = pt.strftime("%b %d, %Y · %H:%M ") + PT_LABEL
            upd_attr = f' data-utc="{dt.strftime("%Y-%m-%dT%H:%M:%SZ")}" data-tfmt="stamp"'
        except ValueError:
            updated = ctx.last_updated
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
{head_meta(title, desc, page)}
<link rel="stylesheet" href="assets/style.css?v={_asset_ver()}">
<script>window.WC_DEFAULT_WATCH={json.dumps(config.DEFAULT_WATCH)};</script>
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>
<header class="site-head">
  <div class="brand"><a href="index.html" aria-label="World Cup 2026 tracker — home">
    <span class="wm-mark" aria-hidden="true"><svg viewBox="0 0 36 36" width="30" height="30"><rect width="36" height="36" rx="3" fill="var(--ink)"/><text x="18" y="25" text-anchor="middle" font-family="ui-monospace,Menlo,monospace" font-weight="800" font-size="17" letter-spacing="-1" fill="var(--accent)">26</text></svg></span>
    <span class="wm-text" data-no-i18n><span class="wm-l1">WORLD&nbsp;CUP</span><span class="wm-l2">TRACKER&nbsp;<span class="wm-yr">/26</span></span></span></a></div>
  <div class="head-right">
    <nav class="site-nav" aria-label="Primary">{nav}</nav>
    {i18n.TOGGLE_HTML}
  </div>
</header>
<main id="main">
{body}
</main>
<footer class="site-foot">
  <div class="foot-rule" aria-hidden="true"></div>
  <div class="foot-grid">
    <div class="foot-cell foot-brand">
      <span class="foot-wm" data-no-i18n>WORLD&nbsp;CUP&nbsp;<span class="foot-yr">/26</span></span>
      <span class="foot-sub">Live match-center · {E(config.TOURNAMENT["hosts"])}</span>
    </div>
    <div class="foot-cell foot-stat">
      <span class="foot-k">STAGE</span><span class="foot-v">{E(ctx.stage())}</span>
    </div>
    <div class="foot-cell foot-stat">
      <span class="foot-k">UPDATED</span>
      <span class="foot-v"><span class="upd-dot wire" aria-hidden="true"><span class="wire-pulse"></span></span><span class="upd-stamp"{upd_attr}>{E(updated) or "—"}</span></span>
    </div>
  </div>
  <div class="foot-tz">
    <label class="foot-tz-k" for="tz-select">Times shown in</label>
    <select id="tz-select" class="tz-select" aria-label="Display time zone">
      <option value="America/New_York">Eastern · ET</option>
      <option value="America/Chicago">Central · CT</option>
      <option value="America/Denver">Mountain · MT</option>
      <option value="America/Los_Angeles" selected>Pacific · PT</option>
      <option value="America/Sao_Paulo">Brazil · BRT</option>
    </select>
  </div>
</footer>
<script src="assets/app.js?v={_asset_ver()}"></script>
<script src="assets/i18n.js?v={_asset_ver()}"></script>
</body>
</html>"""
