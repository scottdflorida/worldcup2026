"""Page chrome: the primary NAV, head/OpenGraph meta, the shell() wrapper
(header, footer, timezone picker) and the versioned asset tags.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from . import bracket, config, i18n, util
from .art import _asset_ver
from .times import E, PT_LABEL, PT_OFFSET_HOURS, _utc_iso

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


def canonical_url(page):
    """Clean canonical URL for a page file (Pages 308-redirects .html -> clean):
    index.html -> https://…/ , usa.html -> https://…/usa , etc."""
    slug = page[:-5] if page.endswith(".html") else page
    if slug == "index":
        return SITE_URL + "/"
    return f"{SITE_URL}/{slug}"


def head_meta(title, desc, page, noindex=False):
    url = canonical_url(page)
    img = f"{SITE_URL}/{OG_IMG}"
    # 404 is served for ANY missing path at any depth, so a <base href="/"> makes
    # every relative URL below (assets, nav) resolve against the root. It is also
    # noindex (skip canonical) and must not advertise itself as a real page.
    base = '<base href="/">\n' if noindex else ""
    robots = '<meta name="robots" content="noindex, follow">\n' if noindex else ""
    canonical = "" if noindex else f'<link rel="canonical" href="{url}">\n'
    return f"""<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{base}<title>{E(title)}</title>
<meta name="description" content="{E(desc)}">
{robots}{canonical}<link rel="manifest" href="manifest.webmanifest">
<meta name="theme-color" content="#F4F2EC" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#14120D" media="(prefers-color-scheme: dark)">
<link rel="icon" type="image/svg+xml" href="{FAVICON}">
<link rel="apple-touch-icon" sizes="180x180" href="{APPLE_ICON}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="World Cup 2026 Tracker">
<meta property="og:locale" content="en_US">
<meta property="og:locale:alternate" content="pt_BR">
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


# --------------------------------------------------------------------------
# JSON-LD structured data (small, honest, deterministic).  All blocks live in
# <script type="application/ld+json"> — inside a SCRIPT node, so the i18n DOM
# walker skips them (no pt-BR needed).  Emitted with sort_keys=True so identical
# inputs yield identical bytes.
# --------------------------------------------------------------------------
_TOURNAMENT = config.TOURNAMENT["name"]   # "FIFA World Cup 2026"
_SPORT = "Association football"


def _team_for_page(ctx, page):
    """The team name whose hub page is `page`, or None (derived from ctx so shell
    can recognise a team page without the page builder passing anything in)."""
    for team in ctx.teams:
        if util.page_for(team) == page:
            return team
    return None


def _ld_website():
    return {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": "World Cup 2026 Tracker",
        "url": SITE_URL + "/",
        "description": ("Live FIFA World Cup 2026 tracker — groups, standings, "
                        "advance odds and a connected knockout bracket."),
        "inLanguage": ["en", "pt-BR"],
    }


def _ld_next_event(ctx):
    """SportsEvent for the next scheduled match (or None when there is no upcoming
    match with a usable UTC kickoff). Slot tokens are resolved to real nations
    where the draw is known; competitors are listed only once concrete."""
    up = ctx.upcoming(1)
    if not up:
        return None
    m = up[0]
    start = _utc_iso(m)
    if not start:
        return None
    by_num = ctx.by_num
    r1 = bracket.resolve_slot(m.get("team1"), ctx.analyses, by_num)
    r2 = bracket.resolve_slot(m.get("team2"), ctx.analyses, by_num)
    n1 = r1["team"] or r1["label"]
    n2 = r2["team"] or r2["label"]
    ev = {
        "@context": "https://schema.org",
        "@type": "SportsEvent",
        "name": f"{n1} vs {n2}",
        "sport": _SPORT,
        "startDate": start,
        "eventStatus": "https://schema.org/EventScheduled",
        "superEvent": {"@type": "SportsEvent", "name": _TOURNAMENT},
    }
    ground = m.get("ground")
    if ground:
        ev["location"] = {"@type": "Place", "name": ground}
    competitors = [{"@type": "SportsTeam", "name": t}
                   for t in (r1["team"], r2["team"]) if t]
    if competitors:
        ev["competitor"] = competitors
    return ev


def _ld_team(team):
    return {
        "@context": "https://schema.org",
        "@type": "SportsTeam",
        "name": team,
        "sport": _SPORT,
        "url": canonical_url(util.page_for(team)),
        "memberOf": {"@type": "SportsEvent", "name": _TOURNAMENT},
    }


def _jsonld_blocks(ctx, page):
    blocks = []
    if page == "index.html":
        blocks.append(_ld_website())
        ev = _ld_next_event(ctx)
        if ev:
            blocks.append(ev)
    else:
        team = _team_for_page(ctx, page)
        if team:
            blocks.append(_ld_team(team))
    return blocks


def _jsonld_html(ctx, page):
    parts = []
    for block in _jsonld_blocks(ctx, page):
        payload = json.dumps(block, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":"))
        parts.append(f'<script type="application/ld+json">{payload}</script>')
    return ("\n" + "\n".join(parts)) if parts else ""


def _breadcrumb(crumb):
    """A slim wayfinding trail under the nav for pages that live one level below a
    primary tab (team pages, group pages). `crumb` is a list of (label, href)
    pairs; href=None marks the current page (rendered as text, aria-current)."""
    if not crumb:
        return ""
    sep = '<span class="crumb-sep" aria-hidden="true">/</span>'
    parts = []
    for label, href in crumb:
        if href:
            parts.append(f'<a href="{href}">{E(label)}</a>')
        else:
            parts.append(f'<span class="crumb-cur" aria-current="page">{E(label)}</span>')
    return (f'<nav class="crumb" aria-label="Breadcrumb">{sep.join(parts)}</nav>')


def shell(title, active, body, ctx, desc=None, page="index.html", crumb=None,
          noindex=False):
    desc = desc or ("Live FIFA World Cup 2026 tracker — groups, standings, advance "
                    "odds, team road-to-the-final and a connected knockout bracket. "
                    "Pin your teams with ★.")
    nav_items = []
    for href, label in NAV:
        # class "on" marks the active *section* (team pages light up TEAMS); but
        # aria-current="page" only fires on the item that IS the current page, so
        # a team/group page's true position is carried by the breadcrumb instead
        # of falsely claiming Teams/Home is the current page.
        on = href == active
        cur = ' aria-current="page"' if href == page else ''
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
{head_meta(title, desc, page, noindex)}{"" if noindex else _jsonld_html(ctx, page)}
<script>(function(){{try{{var t=localStorage.getItem("wc26.theme");if(t==="dark"||t==="light")document.documentElement.setAttribute("data-theme",t);}}catch(e){{}}}})();</script>
<link rel="preload" href="assets/TwemojiCountryFlags.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="assets/style.css?v={_asset_ver()}">
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>
<header class="site-head">
  <div class="brand"><a href="index.html" aria-label="World Cup 2026 tracker — home">
    <span class="wm-mark" aria-hidden="true"><svg viewBox="0 0 36 36" width="30" height="30"><rect width="36" height="36" rx="3" fill="var(--ink-block)"/><text x="18" y="25" text-anchor="middle" font-family="ui-monospace,Menlo,monospace" font-weight="800" font-size="17" letter-spacing="-1" fill="var(--accent)">26</text></svg></span>
    <span class="wm-text" data-no-i18n><span class="wm-l1">WORLD&nbsp;CUP</span><span class="wm-l2">TRACKER&nbsp;<span class="wm-yr">/26</span></span></span></a></div>
  <div class="head-right">
    <nav class="site-nav" aria-label="Primary">{nav}</nav>
    {i18n.TOGGLE_HTML}
    <button id="theme-ico" class="theme-ico" type="button" aria-label="Toggle dark mode" title="Toggle dark mode"><svg viewBox="0 0 20 20" width="15" height="15" aria-hidden="true"><circle cx="10" cy="10" r="7.5" fill="none" stroke="currentColor" stroke-width="2"/><path d="M10 2.5a7.5 7.5 0 0 1 0 15z" fill="currentColor"/></svg></button>
  </div>
</header>
{_breadcrumb(crumb)}
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
      <option value="auto" selected>Auto — device time</option>
      <option value="America/New_York">Eastern · ET</option>
      <option value="America/Chicago">Central · CT</option>
      <option value="America/Denver">Mountain · MT</option>
      <option value="America/Los_Angeles">Pacific · PT</option>
      <option value="UTC">UTC</option>
      <option value="Europe/London">London · UK</option>
      <option value="Europe/Paris">Paris / Berlin · CET</option>
      <option value="America/Sao_Paulo">Brazil · BRT</option>
      <option value="America/Mexico_City">Mexico City · MX</option>
      <option value="Asia/Tokyo">Tokyo · JST</option>
      <option value="Australia/Sydney">Sydney · AEST</option>
    </select>
    <span class="foot-theme">
      <span class="foot-tz-k" id="theme-lbl">THEME</span>
      <button id="theme-btn" class="theme-btn" type="button" aria-labelledby="theme-lbl"><span data-theme-label aria-live="polite">Auto</span></button>
    </span>
  </div>
  <p class="foot-fine">
    <span class="ff-seg">Data:</span> <a class="ff-lnk" href="https://github.com/openfootball/worldcup.json" target="_blank" rel="noopener">openfootball/worldcup.json</a> <span class="ff-seg">(public domain)</span><span class="ff-dot" aria-hidden="true">·</span><span class="ff-seg">Built with a zero-dependency Python engine</span><span class="ff-dot" aria-hidden="true">·</span><a class="ff-lnk" href="about.html">About this site</a><span class="ff-dot" aria-hidden="true">·</span><a class="ff-lnk" href="https://github.com/scottdflorida/worldcup2026" target="_blank" rel="noopener">GitHub</a>
  </p>
</footer>
<script defer src="assets/app.js?v={_asset_ver()}"></script>
<script defer src="assets/i18n.js?v={_asset_ver()}"></script>
</body>
</html>"""
