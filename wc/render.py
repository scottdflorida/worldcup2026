"""Render the static site (multi-page) from the live data + computed analyses.

Pages: a live "command center" home, per-group detail (with scenario viz), a team
hub for every nation, a searchable team directory, and a connected knockout
bracket. The site is team-agnostic — visitors pin any team(s) via a client-side
watchlist that lights them up everywhere ("Live Wire" continuity).

Design system, motion, and all client behavior are emitted from the STYLE and
APP_JS blocks at the bottom of this module (single source of truth, per the
build contract — never hand-edit the generated assets).
"""
from __future__ import annotations

import html
import json
import os
from datetime import datetime, timezone

from . import bracket, config, data, standings, util, venues
from .flags import flag
from .util import fmt_date, fmt_date_short  # noqa: F401

E = html.escape

SITE_URL = "https://worldcup.sflorida.studio"


# --------------------------------------------------------------------------
# Shared context
# --------------------------------------------------------------------------
class Context:
    def __init__(self, payload):
        self.payload = payload
        self.matches = payload["matches"]
        self.analyses = standings.all_groups(self.matches)
        self.thirds = standings.best_thirds(self.analyses)
        self.bracket = bracket.build_bracket(self.matches, self.analyses, [])
        self.teams = sorted({row["team"] for i in self.analyses.values() for row in i["table"]})
        self.projections = {t: bracket.project_team(t, self.matches, self.analyses)
                            for t in self.teams}
        self.advance = standings.advance_probabilities(self.matches, self.analyses)
        self.last_updated = data.last_updated()

    def sorted_matches(self):
        return sorted(self.matches, key=lambda m: (m.get("date", ""), m.get("time", "")))

    def recent_results(self, n=6):
        return [m for m in self.sorted_matches() if data.has_result(m)][-n:][::-1]

    def upcoming(self, n=6):
        return [m for m in self.sorted_matches() if not data.has_result(m)][:n]

    def stage(self):
        if not all(i["complete"] for i in self.analyses.values()):
            return "Group stage"
        for rd in config.KO_ROUNDS:
            ms = [m for m in self.matches if m.get("round") == rd]
            if ms and not all(data.has_result(m) for m in ms):
                return rd
        return "Final"

    def thirds_resolvable(self):
        """The 8-best-third allocation is only meaningful once every group is
        complete; until then we render a labeled provisional state (no fabricated
        qualifiers)."""
        return all(i["complete"] for i in self.analyses.values())


# --------------------------------------------------------------------------
# Time helpers (for the Pulse band's monotonic data-ts)
# --------------------------------------------------------------------------
def _epoch(m):
    """A monotonic sort key (epoch-ish int) from a match's date + kickoff time.

    Local kickoff strings look like '13:00 UTC-6'; we fold the offset back to a
    single comparable instant so the Pulse ribbon is time-ordered across hosts.
    """
    d = m.get("date") or "9999-12-31"
    t = m.get("time") or "00:00"
    try:
        dt = datetime.strptime(d, "%Y-%m-%d")
        base = int(dt.replace(tzinfo=timezone.utc).timestamp())
    except (ValueError, TypeError):
        return 0
    hh = mm = 0
    off = 0
    try:
        clock = t.split()[0]
        hh, mm = (int(x) for x in clock.split(":")[:2])
        if "UTC" in t:
            sign = -1 if "UTC-" in t else 1
            off = sign * int("".join(ch for ch in t.split("UTC")[1] if ch.isdigit()) or 0)
    except (ValueError, IndexError):
        pass
    return base + hh * 3600 + mm * 60 - off * 3600


def _kickoff(m):
    """Just the clock portion of a kickoff time for display ('13:00')."""
    t = m.get("time") or ""
    return t.split()[0] if t else ""


# --------------------------------------------------------------------------
# Components
# --------------------------------------------------------------------------
def team_link(team, cls="team"):
    return (f'<a class="{cls}" data-team="{E(team)}" href="{util.page_for(team)}">'
            f'<span class="fl">{flag(team)}</span><span class="nm">{E(team)}</span></a>')


def star_icon(team):
    return (f'<button class="wl-ic" type="button" data-watch="{E(team)}" '
            f'aria-pressed="false" aria-label="Watch {E(team)}" title="Watch {E(team)}"></button>')


def star(team, label="Watch"):
    return (f'<button class="wl" type="button" data-watch="{E(team)}" aria-pressed="false" '
            f'aria-label="Pin {E(team)} to your watchlist" '
            f'title="Pin {E(team)} to your watchlist">'
            f'<span class="wl-star" aria-hidden="true">★</span><span class="wl-txt">{E(label)}</span></button>')


def slot_chip(res):
    """A bracket/road slot: a resolved team, or a fanned candidate set."""
    if res["team"]:
        return team_link(res["team"])
    cands = sorted(res["candidates"])
    if 1 <= len(cands) <= 6:
        inner = " ".join(team_link(c, "cand") for c in cands)
        return (f'<span class="slot"><span class="slot-label">{E(res["label"])}</span>'
                f'<span class="slot-cands">{inner}</span></span>')
    extra = f" · {len(cands)} possible" if cands else ""
    return f'<span class="slot"><span class="slot-label">{E(res["label"])}{extra}</span></span>'


def status_badge(st, group_complete=False):
    """Status as TEXT + SHAPE, never hue-alone (icons key the meaning)."""
    if st["won_group"]:
        return '<span class="badge win"><span class="bdot" aria-hidden="true"></span>Wins group</span>'
    if st["clinched_top2"]:
        return '<span class="badge q"><span class="bcheck" aria-hidden="true">✓</span>Through</span>'
    if st.get("eliminated"):
        return '<span class="badge gone"><span class="bx" aria-hidden="true">✕</span>Eliminated</span>'
    if st["eliminated_top2"] and not st["can_top2"]:
        return '<span class="badge bub"><span class="btri" aria-hidden="true">◆</span>3rd hope</span>'
    return ''


def group_table(info, link_header=False, solo=False):
    """Render a group standings table.

    solo=True  -> standalone page (shows the qualify-status column + badges)
    link_header=True -> the group title links to its detail page (home grid)
    """
    letter = info["group"].split()[-1]
    rows = []
    for i, row in enumerate(info["table"], 1):
        t = row["team"]
        st = info["status"][t]
        # status class drives the left accent rail (shape, not hue-alone, paired
        # with the badge text in solo view).
        if i <= 2:
            cls = "qual"
        elif i == 3 and not info["complete"]:
            cls = "third"
        elif st.get("eliminated"):
            cls = "gone"
        else:
            cls = ""
        status_cell = (f'<td class="st">{status_badge(st, info["complete"])}</td>'
                       if solo else "")
        rows.append(
            f'<tr class="{cls}" data-team="{E(t)}">'
            f'<td class="pos">{i}</td>'
            f'<td class="star">{star_icon(t)}</td>'
            f'<td class="tm">{team_link(t)}</td>'
            f'<td>{row["P"]}</td><td>{row["W"]}</td><td>{row["D"]}</td><td>{row["L"]}</td>'
            f'<td class="hide-s">{row["GF"]}</td><td class="hide-s">{row["GA"]}</td>'
            f'<td class="gd">{row["GD"]:+d}</td><td class="pts">{row["Pts"]}</td>'
            f'{status_cell}</tr>'
        )
    state = "Final" if info["complete"] else f'{info["remaining"]} to play'
    head = (f'<a class="group-link" href="group-{letter.lower()}.html"><h3>{E(info["group"])} '
            f'<span class="arrow" aria-hidden="true">→</span></h3></a>') if link_header else f'<h3>{E(info["group"])}</h3>'
    status_th = "<th>Status</th>" if solo else ""
    return (
        f'<div class="card group-card{" solo" if solo else ""}">'
        f'<div class="group-head">{head}<span class="muted">{state}</span></div>'
        f'<table class="standings"><thead><tr>'
        f'<th>#</th><th aria-label="Watch"></th><th class="tm">Team</th>'
        f'<th>P</th><th>W</th><th>D</th><th>L</th>'
        f'<th class="hide-s">GF</th><th class="hide-s">GA</th><th>GD</th><th>Pts</th>{status_th}'
        f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
    )


def dist_section(info, advance):
    """Scenario viz: in / bubble / out finish split keyed to the qualify outcome,
    with the advance % (P(reach KO)) always shown.

    Each bar's three segments are: IN (finish 1st/2nd -> through), BUBBLE (3rd ->
    best-third hope), OUT (4th -> gone). The segments sum to 100 by construction,
    and each carries a data-pct so the test can verify width is data-driven.
    """
    dist = info["dist"]
    n = len(info["table"])
    order = sorted(info["table"],
                   key=lambda r: (advance.get(r["team"], 0), r["Pts"], r["GD"]),
                   reverse=True)
    rows = []
    for r in order:
        t = r["team"]
        p = dist[t]  # probability of finishing 1st..nth
        in_pct = (p[0] + p[1]) * 100 if n >= 2 else p[0] * 100
        bubble_pct = p[2] * 100 if n >= 3 else 0.0
        out_pct = sum(p[3:]) * 100 if n >= 4 else 0.0
        # normalize to exactly 100 (kills float drift; keeps sum==100 ±1)
        total = in_pct + bubble_pct + out_pct
        if total > 0:
            in_pct, bubble_pct, out_pct = (x * 100 / total for x in (in_pct, bubble_pct, out_pct))
        adv = round(advance.get(t, 0) * 100)
        segs = []
        for key, label_short, val in (("in", "IN", in_pct), ("bub", "BUBBLE", bubble_pct),
                                      ("out", "OUT", out_pct)):
            lbl = f"{round(val)}%" if val >= 12 else ""
            segs.append(
                f'<span class="dist-seg seg-{key}" data-pct="{val:.2f}" '
                f'style="width:{val:.3f}%" title="{round(val)}% {label_short}">'
                f'<span class="seg-lbl">{lbl}</span></span>'
            )
        advcls = "hi" if adv >= 75 else ("lo" if adv <= 20 else "")
        outcome = (f"{round(in_pct)}% qualify directly, {round(bubble_pct)}% on the third-place "
                   f"bubble, {round(out_pct)}% out — {adv}% chance to reach the knockouts")
        rows.append(
            f'<div class="dist-row" data-team="{E(t)}" title="{E(outcome)}" aria-label="{E(t)}: {E(outcome)}">'
            f'<div class="dist-team">{team_link(t)}</div>'
            f'<div class="dist-bar">{"".join(segs)}</div>'
            f'<div class="dist-adv {advcls}">{adv}<span class="pct">%</span></div></div>'
        )
    note = ('Each bar splits a team\'s remaining finishes into '
            '<b class="k-in">qualify</b> (top two), '
            '<b class="k-bub">on the bubble</b> (third-place hope) and '
            '<b class="k-out">out</b>; the figure on the right is the chance of '
            'reaching the knockouts. '
            + ("The group is decided — these reflect the live knockout picture."
               if info["complete"]
               else f'Drawn from {info["scenarios"]} possible group finishes plus a '
                    'Monte-Carlo run of the other groups for the best-third places.'))
    return (
        '<div class="card dist-card">'
        '<div class="dist-legend" aria-hidden="true">'
        '<span class="lg in"><i class="sw seg-in"></i>Qualify</span>'
        '<span class="lg bub"><i class="sw seg-bub"></i>On the bubble</span>'
        '<span class="lg out"><i class="sw seg-out"></i>Out</span>'
        '<span class="dist-advh">reach knockouts →</span></div>'
        f'<div class="dist">{"".join(rows)}</div>'
        f'<p class="muted dist-note">{note}</p></div>'
    )


def scorers(m):
    """Compact scorer line for a played match: 'Quiñones 9′, Jiménez 67′'."""
    out = []
    for side in ("goals1", "goals2"):
        for g in (m.get(side) or []):
            nm = g.get("name", "")
            mn = g.get("minute", "")
            surname = nm.split()[-1] if nm else ""
            tag = f"{E(surname)} {E(str(mn))}′" if mn else E(surname)
            out.append(f'<span class="scorer">{tag}</span>')
    return f'<div class="m-scorers">{"".join(out)}</div>' if out else ""


def match_line(m, ctx, compact=False):
    by_num = bracket.index_matches(ctx.matches)
    t1 = bracket.resolve_slot(m["team1"], ctx.analyses, by_num)
    t2 = bracket.resolve_slot(m["team2"], ctx.analyses, by_num)
    done = data.has_result(m)
    if done:
        g1, g2 = data.final_score(m)
        cls1 = " win" if g1 > g2 else ""
        cls2 = " win" if g2 > g1 else ""
        score = (f'<span class="score"><b class="sg{cls1}">{g1}</b>'
                 f'<span class="sdash">–</span><b class="sg{cls2}">{g2}</b></span>')
        pens = (m.get("score") or {}).get("p")
        if pens:
            score += f'<span class="pens">({pens[0]}–{pens[1]}p)</span>'
    else:
        score = f'<span class="vs">{E(_kickoff(m) or "vs")}</span>'
    rd = m.get("round", "")
    rd_lbl = "" if str(rd).startswith("Matchday") else f'<span class="rd">{E(rd)}</span>'
    meta = f'{E(fmt_date(m.get("date","")))} · {E(venues.venue_str(m.get("ground","")))}'
    grp = m.get("group")
    grp_lbl = f'<span class="m-grp">{E(grp)}</span>' if grp else ""
    return (
        f'<div class="match{" is-done" if done else " is-upcoming"}">'
        f'<div class="m-meta">{grp_lbl}{rd_lbl}<span class="muted">{meta}</span></div>'
        f'<div class="m-row"><span class="m-side a">{slot_chip(t1)}</span>{score}'
        f'<span class="m-side b">{slot_chip(t2)}</span></div>'
        f'{scorers(m) if done else ""}</div>'
    )


def match_list(ms, ctx, empty="None"):
    return "".join(match_line(m, ctx) for m in ms) or f'<div class="muted empty">{E(empty)}</div>'


def pulse_band(ctx):
    """The signature "Pulse" band: a single time-ordered ribbon fusing the latest
    results and the next kickoffs, with exactly one "now" divider between them.

    Cards carry data-ts (monotonic non-decreasing), venue, scorers (done) or
    kickoff (upcoming). The divider IS the Live Wire signal element (.now-divider
    + .wire-pulse), shared with the bracket's live edge and the watched glow.
    """
    by_num = bracket.index_matches(ctx.matches)
    done = ctx.recent_results(5)[::-1]      # oldest->newest of the recent results
    up = ctx.upcoming(5)                    # soonest first
    if not done and not up:
        return ""

    def card(m, kind):
        t1 = bracket.resolve_slot(m["team1"], ctx.analyses, by_num)
        t2 = bracket.resolve_slot(m["team2"], ctx.analyses, by_num)
        grp = m.get("group") or m.get("round") or ""
        venue_stadium, _ = venues.venue(m.get("ground", ""))
        date = fmt_date_short(m.get("date", ""))
        if kind == "done":
            g1, g2 = data.final_score(m)
            cls1 = " win" if g1 > g2 else ""
            cls2 = " win" if g2 > g1 else ""
            mid = (f'<div class="pz-score"><b class="sg{cls1}">{g1}</b>'
                   f'<span class="sdash">–</span><b class="sg{cls2}">{g2}</b></div>')
            foot = scorers(m) or f'<div class="pz-foot muted">{E(venue_stadium)}</div>'
            tag = '<span class="pz-tag done">FT</span>'
        else:
            mid = f'<div class="pz-ko">{E(_kickoff(m) or "TBD")}</div>'
            foot = f'<div class="pz-foot muted">{E(venue_stadium)}</div>'
            tag = '<span class="pz-tag up">Kicks off</span>'
        return (
            f'<div class="pz {"is-done" if kind=="done" else "is-upcoming"}" '
            f'data-ts="{_epoch(m)}">'
            f'<div class="pz-head"><span class="pz-grp">{E(grp)}</span>{tag}'
            f'<span class="pz-date muted">{E(date)}</span></div>'
            f'<div class="pz-row"><div class="pz-team" data-team="{E(t1["team"] or "")}">'
            f'<span class="fl">{flag(t1["team"]) if t1["team"] else "·"}</span>'
            f'<span class="nm">{E(t1["team"] or t1["label"])}</span></div>'
            f'{mid}'
            f'<div class="pz-team" data-team="{E(t2["team"] or "")}">'
            f'<span class="fl">{flag(t2["team"]) if t2["team"] else "·"}</span>'
            f'<span class="nm">{E(t2["team"] or t2["label"])}</span></div></div>'
            f'{foot}</div>'
        )

    done_cards = "".join(card(m, "done") for m in done)
    up_cards = "".join(card(m, "up") for m in up)
    # The Live Wire "now" divider: exactly one, between done and upcoming.
    divider = (
        '<div class="now-divider wire" aria-label="now">'
        '<span class="wire-pulse" aria-hidden="true"></span>'
        '<span class="now-lbl">NOW</span></div>'
    )
    n_played = sum(1 for m in ctx.matches if data.has_result(m))
    return (
        '<section class="pulse-section" aria-label="Matchday pulse">'
        '<div class="sec-head pulse-head">'
        '<h2>Matchday pulse</h2>'
        f'<span class="muted">latest results, then next kickoffs · {n_played}/{len(ctx.matches)} played</span>'
        '</div>'
        '<div class="pulse-band" data-band="pulse">'
        f'{done_cards}{divider}{up_cards}'
        '</div></section>'
    )


def team_card(ctx, team):
    proj = ctx.projections[team]
    pr, sec = util.accent(team)
    rec = proj["row"]
    return (
        f'<div class="tcard" data-team-card="{E(team)}" data-team="{E(team)}" '
        f'style="--accent:{pr};--accent2:{sec}">'
        f'<a class="tcard-main" href="{util.page_for(team)}">'
        f'<span class="tcard-flag">{flag(team)}</span>'
        f'<span class="tcard-body"><span class="tcard-name">{E(team)}</span>'
        f'<span class="tcard-meta muted">{E(proj["group"])} · {_ordinal(proj["rank"])} · {rec["Pts"]} pts</span></span>'
        f'</a>{star_icon(team)}</div>'
    )


# --------------------------------------------------------------------------
# Shell
# --------------------------------------------------------------------------
NAV = [
    ("index.html", "Home"),
    ("teams.html", "Teams"),
    ("bracket.html", "Bracket"),
]

OG_IMG = "assets/og.svg"
FAVICON = "assets/favicon.svg"


def head_meta(title, desc, page):
    url = f"{SITE_URL}/{page}"
    img = f"{SITE_URL}/{OG_IMG}"
    return f"""<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{E(title)}</title>
<meta name="description" content="{E(desc)}">
<meta name="theme-color" content="#070d0c">
<link rel="icon" type="image/svg+xml" href="{FAVICON}">
<link rel="apple-touch-icon" href="{FAVICON}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="World Cup 2026 Tracker">
<meta property="og:title" content="{E(title)}">
<meta property="og:description" content="{E(desc)}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{img}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{E(title)}">
<meta name="twitter:description" content="{E(desc)}">
<meta name="twitter:image" content="{img}">"""


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
    if ctx.last_updated:
        try:
            dt = datetime.fromisoformat(ctx.last_updated).astimezone(timezone.utc)
            updated = dt.strftime("%b %d, %Y · %H:%M UTC")
        except ValueError:
            updated = ctx.last_updated
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
{head_meta(title, desc, page)}
<link rel="stylesheet" href="assets/style.css">
<script>window.WC_DEFAULT_WATCH={json.dumps(config.DEFAULT_WATCH)};</script>
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>
<div class="bg-fx" aria-hidden="true"></div>
<header class="site-head">
  <div class="brand"><a href="index.html" aria-label="World Cup 2026 tracker — home">
    <img class="ball" src="{FAVICON}" alt="" width="24" height="24" aria-hidden="true">
    <span class="brand-wm">World&nbsp;Cup&nbsp;<span class="grad">26</span></span>
    <span class="brand-sub">tracker</span></a></div>
  <nav class="site-nav" aria-label="Primary">{nav}</nav>
</header>
<main id="main">
{body}
</main>
<footer class="site-foot">
  <div class="foot-top">
    <div class="foot-updated"><span class="upd-dot wire" aria-hidden="true"><span class="wire-pulse"></span></span>
      Last updated <strong>{E(updated) or "—"}</strong></div>
  </div>
  <div class="foot-meta">Stage: <strong>{E(ctx.stage())}</strong> · {E(config.TOURNAMENT["hosts"])}</div>
  <div class="muted foot-fine">Data: openfootball (public domain). Auto-updates within ~15&nbsp;min of a result landing. Projections follow the current standings; third-place bracket slots resolve via FIFA's allocation once the group stage ends. Original artwork — not affiliated with FIFA.</div>
</footer>
<script src="assets/app.js"></script>
</body>
</html>"""


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------
def page_home(ctx):
    grid = "".join(group_table(ctx.analyses[g], link_header=True) for g in sorted(ctx.analyses))
    src = "".join(team_card(ctx, t) for t in ctx.teams)

    resolvable = ctx.thirds_resolvable()
    thirds_rows = "".join(
        f'<tr class="{"qual" if (resolvable and r["qualifies"]) else ""}" data-team="{E(r["team"])}">'
        f'<td class="pos">{r["seed"]}</td><td class="star">{star_icon(r["team"])}</td>'
        f'<td class="tm">{team_link(r["team"])}</td>'
        f'<td>{E(r["group"].split()[-1])}</td><td>{r["Pts"]}</td><td class="gd">{r["GD"]:+d}</td><td>{r["GF"]}</td>'
        f'<td class="r32">{(("✓ in" if r["qualifies"] else "out") if resolvable else "—")}</td></tr>'
        for r in ctx.thirds
    )
    thirds_state = "resolved" if resolvable else "provisional"
    thirds_note = ("Eight third-placed teams advance to the Round of 32."
                   if resolvable else
                   "Provisional — the eight best third-placed teams are fixed once "
                   "every group finishes. This race updates as groups conclude.")
    n_played = sum(1 for m in ctx.matches if data.has_result(m))

    body = f"""
<section class="hero" aria-label="Tournament status">
  <div class="hero-eyebrow"><span class="he-dot wire" aria-hidden="true"><span class="wire-pulse"></span></span>{E(config.TOURNAMENT["hosts"])}</div>
  <h1 class="hero-title">The 2026 World Cup, <span class="grad-text">live</span>.</h1>
  <p class="hero-lead">Standings, advance odds, every road to the final — and the teams you follow lit up across all of it.</p>
  <div class="hero-chips">
    <span class="chip stage"><span class="chip-dot" aria-hidden="true"></span><b>{E(ctx.stage())}</b></span>
    <span class="chip"><span class="chip-n">{n_played}</span><span class="chip-d">/ {len(ctx.matches)} matches played</span></span>
  </div>
</section>

{pulse_band(ctx)}

<section id="your-teams-sec" class="your-teams-sec" data-reveal aria-label="Your teams">
  <div class="sec-head"><h2>Your teams</h2><span class="muted">Pin any team with ★ — saved in your browser, lit up everywhere</span></div>
  <div id="your-teams" class="tcard-grid yt-grid"></div>
  <div id="team-src" hidden>{src}</div>
</section>

<section class="groups-sec" data-reveal aria-label="Groups">
  <div class="sec-head"><h2>The twelve groups</h2><span class="muted">Tap a group for fixtures &amp; scenarios</span></div>
  <div class="group-grid">{grid}</div>
</section>

<section class="thirds-sec" data-reveal data-thirds-state="{thirds_state}" aria-label="Best third-placed teams">
  <div class="sec-head"><h2>Best third-placed race</h2><span class="muted">{"eight advance" if resolvable else "provisional · eight will advance"}</span></div>
  <div class="card"><table class="standings thirds">
  <thead><tr><th>Seed</th><th aria-label="Watch"></th><th class="tm">Team</th><th>Grp</th><th>Pts</th><th>GD</th><th>GF</th><th>R32</th></tr></thead>
  <tbody>{thirds_rows}</tbody></table>
  <p class="muted dist-note">{thirds_note}</p></div>
</section>
"""
    return shell(config.TOURNAMENT["name"] + " — Live Tracker", "index.html", body, ctx,
                 page="index.html")


def page_group(ctx, letter):
    g = f"Group {letter}"
    info = ctx.analyses[g]
    ms = sorted([m for m in ctx.matches if m.get("group") == g],
                key=lambda m: (m.get("date", ""), m.get("time", "")))
    completed = [m for m in ms if data.has_result(m)]
    upcoming = [m for m in ms if not data.has_result(m)]
    chips = " ".join(team_link(row["team"]) for row in info["table"])
    state = "Final standings" if info["complete"] else f'{info["remaining"]} games to play'
    body = f"""
<section class="group-banner">
  <div class="gb-letter">{E(letter)}</div>
  <div class="gb-main"><div class="gb-tag">Group stage</div>
    <h1 class="gb-title">Group {E(letter)}</h1>
    <div class="gb-state">{E(state)}</div>
    <div class="gb-teams">{chips}</div></div>
</section>

<section aria-label="Standings">
  <div class="sec-head"><h2>Standings</h2></div>
  {group_table(info, solo=True)}
</section>

<section aria-label="Scenarios">
  <div class="sec-head"><h2>Scenarios</h2><span class="muted">how the remaining games could finish the table</span></div>
  {dist_section(info, ctx.advance)}
</section>

<section aria-label="Upcoming games"><div class="sec-head"><h2>Coming up</h2></div>
  <div class="match-list">{match_list(upcoming, ctx, "Group complete")}</div></section>

<section aria-label="Completed games"><div class="sec-head"><h2>Results</h2></div>
  <div class="match-list">{match_list(completed, ctx, "None played yet")}</div></section>
"""
    return shell(f"Group {letter} — World Cup 2026", "", body, ctx,
                 desc=(f"Group {letter} at the 2026 World Cup: live standings, advance "
                       f"odds, finish scenarios, fixtures and scorers."),
                 page=f"group-{letter.lower()}.html")


def page_team(ctx, team):
    proj = ctx.projections[team]
    info = ctx.analyses[proj["group"]]
    pr, sec = util.accent(team)
    g = proj["group_letter"]
    ranks = set(proj["possible_ranks"])
    cur = proj["rank"]

    roads = []
    if 1 in ranks:
        roads.append(road_branch(team, g, ctx, f"1{g}",
                     "Win the group", entered=(cur == 1)))
    if 2 in ranks:
        roads.append(road_branch(team, g, ctx, f"2{g}",
                     "Finish runner-up", entered=(cur == 2)))
    third_html = _third_road(ctx, proj) if 3 in ranks else ""
    roads = [r for r in roads if r]

    group_results = [m for m in ctx.matches if m.get("group") == proj["group"]]
    gr_played = [m for m in group_results if data.has_result(m)]
    gr_upcoming = [m for m in group_results if not data.has_result(m)]

    if roads or third_html:
        road_body = f'<div class="roads">{"".join(roads)}{third_html}</div>'
    else:
        road_body = '<p class="muted">No knockout path yet — still alive in the group.</p>'

    body = f"""
<section class="team-hero" data-team="{E(team)}" style="--accent:{pr};--accent2:{sec}">
  <div class="th-inner">
    <div class="th-flag" aria-hidden="true">{flag(team)}</div>
    <div class="th-main">
      <div class="th-eyebrow">{E(proj['group'])}</div>
      <h1>{E(team)}</h1>
      <p class="th-line"><a class="th-grp" href="group-{g.lower()}.html">{E(proj['group'])}</a> · {_ordinal(proj['rank'])} place · {proj['row']['Pts']} pts ({proj['row']['W']}W {proj['row']['D']}D {proj['row']['L']}L)</p>
      <div class="th-outlook">{_outlook_badge(proj)}<span class="th-outline">{_one_line_outlook(proj)}</span></div>
    </div>
    <div class="th-watch">{star(team, "Watch")}</div>
  </div>
</section>

<section aria-label="Group standings">
  <div class="sec-head"><h2>{E(proj['group'])} standings</h2><span class="muted">your team highlighted</span></div>
  {group_table(info, solo=True)}
</section>

<section aria-label="Road to the final">
  <div class="sec-head"><h2>Road to the final</h2><span class="muted">potential futures — who {E(team)} could meet each round</span></div>
  <p class="muted road-intro">Live candidates fan out from each round before names resolve; the branch collapses to one as results land.</p>
  {road_body}
</section>

<section class="cols" aria-label="Fixtures">
  <div><h2 class="col-h">Results</h2><div class="match-list">{match_list(gr_played, ctx, "None yet")}</div></div>
  <div><h2 class="col-h">Remaining group games</h2><div class="match-list">{match_list(gr_upcoming, ctx, "Group complete")}</div></div>
</section>
"""
    return shell(f"{team} — Road to the Final · World Cup 2026", "", body, ctx,
                 desc=(f"{team} at the 2026 World Cup: where they stand, what they need "
                       f"to advance, and their potential road to the final. Pin {team} "
                       f"with ★ to follow them everywhere."),
                 page=util.page_for(team))


def page_teams(ctx):
    directory = []
    for g in sorted(ctx.analyses):
        info = ctx.analyses[g]
        cards = "".join(team_card(ctx, row["team"]) for row in info["table"])
        directory.append(
            f'<div class="dir-group"><div class="dir-head">'
            f'<a href="group-{g.split()[-1].lower()}.html">{E(g)}</a> '
            f'<span class="muted">{"Final" if info["complete"] else str(info["remaining"]) + " to play"}</span></div>'
            f'<div class="tcard-grid">{cards}</div></div>'
        )
    body = f"""
<section class="teams-intro" aria-label="All teams">
  <h1>All 48 teams</h1>
  <p class="muted">Tap a team to inspect its path to the final; ★ to follow it across the site.</p>
</section>
<section id="directory" aria-label="Team directory">
  <div class="search-wrap">
    <span class="search-ic" aria-hidden="true">⌕</span>
    <input id="team-search" class="team-search" type="search" placeholder="Search any of 48 teams…" aria-label="Search teams">
  </div>
  <p id="search-empty" class="muted search-empty" hidden>No teams match that search.</p>
  <div class="directory">{"".join(directory)}</div>
</section>
"""
    return shell("All Teams — World Cup 2026", "teams.html", body, ctx,
                 desc="Browse and search all 48 nations at the 2026 World Cup. Open any "
                      "team's hub for standings, advance odds and road to the final.",
                 page="teams.html")


def page_bracket(ctx):
    rounds = [(rd, rows) for rd, rows in ctx.bracket if rd != "Match for third place"]
    cols = []
    n_round = len(rounds)
    for ci, (rd, rows) in enumerate(rounds):
        is_final = rd == "Final"
        cells = []
        for r in rows:
            sides = []
            any_candidate = False
            for key in ("team1", "team2"):
                res = r[key]
                resolved = bool(res["team"])
                if not resolved:
                    any_candidate = True
                g = ""
                if r["played"]:
                    g1, g2 = data.final_score({"score": r["score"]})
                    gv = g1 if key == "team1" else g2
                    winner = r["winner"]
                    is_win = bool(winner and res["team"] == winner)
                    g = f'<span class="km-g{" kwin" if is_win else " kloss"}">{gv}</span>'
                side_cls = "km-team" + ("" if resolved else " is-candidate")
                sides.append(f'<div class="{side_cls}">{_bracket_side(res)}{g}</div>')
            live = (not r["played"] and r.get("touches_focus") is not None
                    and not r.get("team1", {}).get("team") and ci == 0)
            km_cls = "km" + (" km-live" if any_candidate and ci == 0 else "")
            date = fmt_date_short(r.get("date", ""))
            cells.append(
                f'<div class="{km_cls}" data-mnum="{r["num"]}">'
                f'<div class="km-no"><span class="km-m">M{r["num"]}</span>'
                f'<span class="km-d muted">{E(date)}</span></div>'
                f'{sides[0]}<div class="km-line"><span class="km-wire wire"><span class="wire-pulse"></span></span></div>{sides[1]}</div>'
            )
        if is_final:
            # The Final column is a designed climax: a champion plinth.
            champ = ""
            final_row = rows[0] if rows else None
            if final_row and final_row["played"] and final_row.get("winner"):
                champ_team = final_row["winner"]
                champ = (f'<div class="champ-name" data-team="{E(champ_team)}">'
                         f'<span class="fl">{flag(champ_team)}</span>'
                         f'<span class="nm">{E(champ_team)}</span></div>')
            else:
                champ = '<div class="champ-name pending muted">Champion T.B.D.</div>'
            plinth = (
                '<div class="champion-plinth">'
                '<img class="cp-trophy" src="assets/trophy.svg" alt="" width="40" height="40" aria-hidden="true">'
                '<div class="cp-lbl">World Champion</div>'
                f'{champ}</div>'
            )
            cols.append(
                f'<div class="kr-col kr-final">'
                f'<div class="kr-head"><img class="kr-trophy" src="assets/trophy.svg" alt="" width="18" height="18" aria-hidden="true">{E(rd)}</div>'
                f'{"".join(cells)}{plinth}</div>'
            )
        else:
            cols.append(
                f'<div class="kr-col"><div class="kr-head">{E(rd)} '
                f'<span class="kr-count">{len(rows)}</span></div>{"".join(cells)}</div>'
            )

    # SVG connector layer drawn under the cards (the "one tree" feeling). The
    # client positions the strokes; here we emit one path placeholder per
    # later-round match so the structure exists even with JS off.
    body = f"""
<section class="bracket-intro" aria-label="Knockout bracket">
  <h1>Knockout bracket</h1>
  <p class="muted">Round of 32 → Final as one connected tree. Pin teams with ★ and their matches glow across the bracket; greyed slots show live candidates and resolve as results land.</p>
</section>
<section class="bracket-wrap" data-hscroll>
  <div class="kbracket" data-hscroll data-rounds="{n_round}">
    <svg class="bz-layer" aria-hidden="true" preserveAspectRatio="none"></svg>
    {"".join(cols)}
  </div>
</section>
"""
    return shell("Knockout Bracket — World Cup 2026", "bracket.html", body, ctx,
                 desc="The full 2026 World Cup knockout bracket as one connected tree, "
                      "Round of 32 to the Final — with live candidates before slots resolve "
                      "and your pinned teams glowing through.",
                 page="bracket.html")


def _bracket_side(res):
    if res["team"]:
        return team_link(res["team"], "bteam")
    prov = res.get("provisional")
    code = res.get("slot", "")
    cands = sorted(res.get("candidates") or [])
    if prov:
        return (f'{team_link(prov, "bteam prov")}'
                f'<span class="bcode" title="current table position">{E(code)}</span>')
    if 1 <= len(cands) <= 4:
        chips = " ".join(team_link(c, "cand") for c in cands)
        return (f'<span class="bcands"><span class="bcode">{E(res["label"])}</span>'
                f'<span class="bcands-list">{chips}</span></span>')
    extra = f" · {len(cands)} live" if cands else ""
    return f'<span class="bslot">{E(res["label"])}{extra}</span>'


# --------------------------------------------------------------------------
# Road-to-the-final branch graph
# --------------------------------------------------------------------------
def road_branch(team, group_letter, ctx, entry_slot, heading, entered=False):
    """Render a branching road graph: each round node fans to the SET of live
    candidate opponents with connector strokes, collapsing to one node when the
    table resolves. Not a vertical list."""
    path = bracket.project_path(team, ctx.matches, ctx.analyses, group_letter, entry_slot)
    if not path:
        return ""
    steps = []
    for i, s in enumerate(path):
        opp = s["opponent"]
        rd_short = _round_short(s["round"])
        date = fmt_date_short(s.get("date", ""))
        if opp["team"]:
            fan = (f'<div class="road-fan single">'
                   f'<span class="road-cand resolved">{team_link(opp["team"], "cand")}</span></div>')
            n_cand = 1
        else:
            cands = sorted(opp["candidates"])
            if cands:
                shown = cands[:6]
                chips = "".join(f'<span class="road-cand">{team_link(c, "cand")}</span>'
                                for c in shown)
                more = (f'<span class="road-more">+{len(cands)-6}</span>'
                        if len(cands) > 6 else "")
                fan = f'<div class="road-fan{" multi" if len(shown) > 1 else ""}">{chips}{more}</div>'
                n_cand = len(shown)
            else:
                fan = f'<div class="road-fan"><span class="road-cand tbd muted">{E(opp["label"])}</span></div>'
                n_cand = 0
        branch = ('<span class="road-branch" aria-hidden="true"></span>'
                  if n_cand > 1 else
                  '<span class="road-branch single" aria-hidden="true"></span>')
        steps.append(
            f'<li class="road-step" data-cands="{n_cand}">'
            f'<div class="road-node"><span class="road-rd">{E(rd_short)}</span>'
            f'<span class="road-date muted">{E(date)}</span></div>'
            f'{branch}'
            f'<div class="road-opp"><span class="road-vs">vs</span>{fan}</div>'
            f'</li>'
        )
    tag = '<span class="road-track">current track</span>' if entered else ''
    return (f'<div class="road-line">'
            f'<div class="road-line-head"><h4>{E(heading)}</h4>{tag}</div>'
            f'<ol class="road-graph">{"".join(steps)}</ol></div>')


def _third_road(ctx, proj):
    by_num = bracket.index_matches(ctx.matches)
    steps = []
    for tgt in proj["third_targets"]:
        m = by_num[tgt["num"]]
        opp_slot = m["team2"] if str(m["team1"]).startswith("3") else m["team1"]
        opp = bracket.resolve_slot(opp_slot, ctx.analyses, by_num)
        date = fmt_date_short(m.get("date", ""))
        if opp["team"]:
            fan = f'<div class="road-fan single"><span class="road-cand resolved">{team_link(opp["team"], "cand")}</span></div>'
            nc = 1
        else:
            cands = sorted(opp["candidates"])[:6]
            chips = "".join(f'<span class="road-cand">{team_link(c, "cand")}</span>' for c in cands) \
                or f'<span class="road-cand tbd muted">{E(opp["label"])}</span>'
            fan = f'<div class="road-fan{" multi" if len(cands) > 1 else ""}">{chips}</div>'
            nc = len(cands)
        steps.append(
            f'<li class="road-step" data-cands="{nc}">'
            f'<div class="road-node"><span class="road-rd">R32</span>'
            f'<span class="road-date muted">M{m["num"]} · {E(date)}</span></div>'
            f'<span class="road-branch{" single" if nc <= 1 else ""}" aria-hidden="true"></span>'
            f'<div class="road-opp"><span class="road-vs">vs</span>{fan}</div></li>'
        )
    if not steps:
        return ""
    return ('<div class="road-line third">'
            '<div class="road-line-head"><h4>Sneak through as a best third</h4>'
            '<span class="road-track alt">if 3rd qualifies</span></div>'
            '<p class="muted road-sub">A third-placed finish could land in any of these Round-of-32 slots '
            '(FIFA fixes the exact one once all groups finish):</p>'
            f'<ol class="road-graph">{"".join(steps)}</ol></div>')


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _ordinal(n):
    return {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}.get(n, f"{n}th")


def _round_short(rd):
    return {"Round of 32": "R32", "Round of 16": "R16", "Quarter-final": "QF",
            "Semi-final": "SF", "Final": "Final"}.get(rd, rd)


def _one_line_outlook(proj):
    st = proj["status"]
    g = proj["group"]
    if st["won_group"]:
        return f'Through to the Round of 32 as {E(g)} winners.'
    if st["clinched_top2"]:
        return f'Qualified for the Round of 32 from {E(g)}.'
    if st.get("eliminated"):
        return f'Out of contention in {E(g)}.'
    if proj["rank"] <= 2 and not proj["group_complete"]:
        return f'Currently {_ordinal(proj["rank"])} in {E(g)} — inside the top two.'
    if proj["rank"] == 3:
        return f'3rd in {E(g)} — chasing a best-third-place spot.'
    return f'{_ordinal(proj["rank"])} in {E(g)} — work to do.'


def _outlook_badge(proj):
    """Status badge for the team hero — text + icon, never hue-alone."""
    st = proj["status"]
    if st["won_group"]:
        return '<span class="th-badge win"><span class="bdot" aria-hidden="true"></span>Group winners</span>'
    if st["clinched_top2"]:
        return '<span class="th-badge q"><span class="bcheck" aria-hidden="true">✓</span>Qualified</span>'
    if st.get("eliminated"):
        return '<span class="th-badge gone"><span class="bx" aria-hidden="true">✕</span>Eliminated</span>'
    if proj["rank"] <= 2 and not proj["group_complete"]:
        return '<span class="th-badge q"><span class="bcheck" aria-hidden="true">↑</span>In the top two</span>'
    if proj["rank"] == 3:
        return '<span class="th-badge bub"><span class="btri" aria-hidden="true">◆</span>On the bubble</span>'
    return '<span class="th-badge work"><span class="btri" aria-hidden="true">●</span>Work to do</span>'


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
def render_site(payload):
    ctx = Context(payload)
    files = {
        "index.html": page_home(ctx),
        "teams.html": page_teams(ctx),
        "bracket.html": page_bracket(ctx),
        "assets/style.css": STYLE,
        "assets/app.js": APP_JS,
        "assets/ball.svg": BALL_SVG,
        "assets/pitch.svg": PITCH_SVG,
        "assets/trophy.svg": TROPHY_SVG,
        "assets/favicon.svg": FAVICON_SVG,
        "assets/og.svg": OG_SVG,
    }
    for g in ctx.analyses:
        letter = g.split()[-1]
        files[f"group-{letter.lower()}.html"] = page_group(ctx, letter)
    for team in ctx.teams:
        files[util.page_for(team)] = page_team(ctx, team)
    return files


def write_site(public_dir, payload):
    """Render and write the site, clearing stale HTML pages first."""
    files = render_site(payload)
    if os.path.isdir(public_dir):
        for fn in os.listdir(public_dir):
            if fn.endswith(".html"):
                os.remove(os.path.join(public_dir, fn))
    for rel, content in files.items():
        out = os.path.join(public_dir, rel)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(content)
    return len(files)


# --------------------------------------------------------------------------
# Original, license-free SVG graphics (no FIFA/World Cup trademarks used)
# --------------------------------------------------------------------------
BALL_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" fill="none">
<circle cx="32" cy="32" r="30" fill="#fff" stroke="#0a0c12" stroke-width="2.5"/>
<polygon points="32,23 40.56,29.22 37.29,39.28 26.71,39.28 23.44,29.22" fill="#0a0c12"/>
<g stroke="#0a0c12" stroke-width="2.2" stroke-linecap="round">
<line x1="32" y1="23" x2="32" y2="3.5"/>
<line x1="40.56" y1="29.22" x2="59" y2="23"/>
<line x1="37.29" y1="39.28" x2="48.6" y2="55"/>
<line x1="26.71" y1="39.28" x2="15.4" y2="55"/>
<line x1="23.44" y1="29.22" x2="5" y2="23"/>
</g></svg>"""

TROPHY_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" fill="none">
<defs><linearGradient id="tg" x1="0" y1="0" x2="0" y2="1">
<stop offset="0" stop-color="#fde68a"/><stop offset="1" stop-color="#d97706"/></linearGradient></defs>
<g fill="url(#tg)" stroke="#b45309" stroke-width="1.2" stroke-linejoin="round">
<path d="M13 7 H35 V14 A11 11 0 0 1 13 14 Z"/>
<path d="M13 9 H7.5 a4.5 5.5 0 0 0 7 9.2" fill="none"/>
<path d="M35 9 H40.5 a4.5 5.5 0 0 1 -7 9.2" fill="none"/>
<rect x="22" y="24" width="4" height="7"/>
<rect x="15.5" y="31" width="17" height="4.2" rx="1.2"/>
<rect x="13" y="35" width="22" height="4.4" rx="1.4"/>
</g></svg>"""

PITCH_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 200" fill="none" stroke="#fff" stroke-width="2">
<rect x="6" y="6" width="308" height="188" rx="5"/>
<line x1="160" y1="6" x2="160" y2="194"/>
<circle cx="160" cy="100" r="30"/>
<circle cx="160" cy="100" r="2.6" fill="#fff" stroke="none"/>
<rect x="6" y="55" width="44" height="90"/>
<rect x="6" y="80" width="18" height="40"/>
<rect x="270" y="55" width="44" height="90"/>
<rect x="296" y="80" width="18" height="40"/>
<path d="M50 79 A30 30 0 0 1 50 121"/>
<path d="M270 79 A30 30 0 0 0 270 121"/>
</svg>"""

# Favicon: an original "26" monogram inside a luminous ring on dark field.
FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<defs>
<linearGradient id="fg" x1="0" y1="0" x2="1" y2="1">
<stop offset="0" stop-color="#34d399"/><stop offset=".55" stop-color="#2dd4bf"/><stop offset="1" stop-color="#22d3ee"/></linearGradient>
</defs>
<rect width="64" height="64" rx="15" fill="#070d0c"/>
<circle cx="32" cy="32" r="25" fill="none" stroke="url(#fg)" stroke-width="3.4"/>
<circle cx="32" cy="32" r="25" fill="none" stroke="#22d3ee" stroke-width="3.4" stroke-linecap="round"
  stroke-dasharray="40 200" transform="rotate(-90 32 32)" opacity=".95"/>
<text x="32" y="41" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" font-weight="800"
  font-size="24" fill="url(#fg)" letter-spacing="-1">26</text>
</svg>"""

# OG card (1200x630) — original art, broadcast-scoreboard mood, no trademarks.
OG_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 630">
<defs>
<linearGradient id="og-bg" x1="0" y1="0" x2="1" y2="1">
<stop offset="0" stop-color="#06100e"/><stop offset="1" stop-color="#0a1a16"/></linearGradient>
<linearGradient id="og-grad" x1="0" y1="0" x2="1" y2="0">
<stop offset="0" stop-color="#34d399"/><stop offset=".5" stop-color="#2dd4bf"/><stop offset="1" stop-color="#22d3ee"/></linearGradient>
<radialGradient id="og-glow" cx="22%" cy="0%" r="80%">
<stop offset="0" stop-color="#34d399" stop-opacity=".42"/><stop offset="1" stop-color="#34d399" stop-opacity="0"/></radialGradient>
<radialGradient id="og-glow2" cx="100%" cy="20%" r="70%">
<stop offset="0" stop-color="#22d3ee" stop-opacity=".34"/><stop offset="1" stop-color="#22d3ee" stop-opacity="0"/></radialGradient>
</defs>
<rect width="1200" height="630" fill="url(#og-bg)"/>
<rect width="1200" height="630" fill="url(#og-glow)"/>
<rect width="1200" height="630" fill="url(#og-glow2)"/>
<g opacity=".10" stroke="#7fe9d6" stroke-width="2" fill="none">
<rect x="760" y="120" width="380" height="390" rx="8"/>
<line x1="950" y1="120" x2="950" y2="510"/>
<circle cx="950" cy="315" r="60"/>
</g>
<g transform="translate(80,150)">
<circle cx="34" cy="34" r="30" fill="none" stroke="url(#og-grad)" stroke-width="5"/>
<text x="34" y="46" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" font-weight="800" font-size="30" fill="url(#og-grad)">26</text>
<text x="92" y="30" font-family="Helvetica,Arial,sans-serif" font-weight="800" font-size="26" fill="#9fded0" letter-spacing="3">WORLD CUP 2026</text>
<text x="92" y="58" font-family="Helvetica,Arial,sans-serif" font-weight="600" font-size="20" fill="#5f8c82" letter-spacing="2">LIVE TRACKER</text>
</g>
<text x="80" y="360" font-family="Helvetica,Arial,sans-serif" font-weight="800" font-size="86" fill="#eaf3f0">The 2026 World Cup,</text>
<text x="80" y="452" font-family="Helvetica,Arial,sans-serif" font-weight="800" font-size="86" fill="url(#og-grad)">live.</text>
<text x="80" y="520" font-family="Helvetica,Arial,sans-serif" font-weight="500" font-size="28" fill="#8ba79f">Standings · advance odds · every road to the final</text>
<rect x="80" y="556" width="120" height="6" rx="3" fill="url(#og-grad)"/>
</svg>"""


APP_JS = r"""
(function(){
  var KEY='wc26.watch';
  var DEFAULT=Array.isArray(window.WC_DEFAULT_WATCH)?window.WC_DEFAULT_WATCH:[];
  function get(){try{var v=JSON.parse(localStorage.getItem(KEY));if(Array.isArray(v))return v;}catch(e){}return DEFAULT.slice();}
  function save(a){try{localStorage.setItem(KEY,JSON.stringify(a));}catch(e){}}
  function toggle(t){var a=get();var i=a.indexOf(t);if(i>=0)a.splice(i,1);else a.push(t);save(a);apply();}
  function esc(t){return (window.CSS&&CSS.escape)?CSS.escape(t):t.replace(/"/g,'\\"');}
  function apply(){
    var w=get();
    var host=document.getElementById('your-teams');
    if(host){
      host.innerHTML='';
      if(!w.length){
        host.innerHTML='<div class="yt-empty"><span class="yt-star" aria-hidden="true">★</span>'+
          '<div class="yt-empty-body"><b>Follow your teams.</b>'+
          '<span class="muted">Tap the ★ on any team — on a group, a team page or the bracket — '+
          'and they’ll live here and glow across the whole site.</span></div></div>';
      } else {
        w.forEach(function(t){
          var src=document.querySelector('#team-src [data-team-card="'+esc(t)+'"]')
                ||document.querySelector('[data-team-card="'+esc(t)+'"]');
          if(src)host.appendChild(src.cloneNode(true));
        });
      }
    }
    document.querySelectorAll('[data-team]').forEach(function(el){
      var t=el.getAttribute('data-team');
      el.classList.toggle('watched', !!t && w.indexOf(t)>=0);
    });
    document.querySelectorAll('.match,.km,.dist-row,.pz,.road-step,.tcard').forEach(function(el){
      el.classList.toggle('has-watched',!!el.querySelector('.watched'));
    });
    document.querySelectorAll('[data-watch]').forEach(function(btn){
      var on=w.indexOf(btn.getAttribute('data-watch'))>=0;
      btn.classList.toggle('on',on);btn.setAttribute('aria-pressed',on?'true':'false');
      var lab=btn.querySelector('.wl-txt');if(lab)lab.textContent=on?'Watching':'Watch';
    });
  }
  document.addEventListener('click',function(e){
    var b=e.target.closest&&e.target.closest('[data-watch]');
    if(b){e.preventDefault();toggle(b.getAttribute('data-watch'));}
  });
  // Search the team directory.
  document.addEventListener('input',function(e){
    if(e.target.id!=='team-search')return;
    var q=e.target.value.trim().toLowerCase();
    var anyVisible=false;
    document.querySelectorAll('#directory .tcard').forEach(function(c){
      var n=(c.getAttribute('data-team-card')||'').toLowerCase();
      var show=(!q||n.indexOf(q)>=0);
      c.hidden=!show; if(show)anyVisible=true;
    });
    document.querySelectorAll('.dir-group').forEach(function(g){
      g.hidden=!g.querySelector('.tcard:not([hidden])');
    });
    var em=document.getElementById('search-empty');
    if(em)em.hidden=anyVisible;
  });

  // ---- Bracket layout: position each later-round card at the vertical midpoint
  // of its two feeding parents so the columns read as one true tournament tree
  // (card i in round R sits between cards 2i and 2i+1 of round R-1). Then draw
  // connector strokes from each card up to its parents. Both are progressive
  // enhancement; the bracket is fully legible (a clean column stack) without JS.
  function layoutBracket(){
    var tree=document.querySelector('.kbracket');
    if(!tree)return;
    var cols=[].slice.call(tree.querySelectorAll('.kr-col'));
    if(cols.length<2)return;
    var W=window.innerWidth;
    // Reset any prior positioning first (so resize recomputes from scratch).
    cols.forEach(function(col){
      [].slice.call(col.querySelectorAll('.km')).forEach(function(k){
        k.style.position='';k.style.top='';k.style.left='';k.style.right='';k.style.width='';
      });
      col.style.position='';
    });
    if(W<720){tree.classList.remove('bracket-laid');return;} // narrow: simple stacked layout
    tree.classList.add('bracket-laid');
    function cards(col){return [].slice.call(col.querySelectorAll('.km'));}
    // Establish baseline centers for round 0 in column-local coords.
    var prevCenters=null;
    cols.forEach(function(col,ci){
      col.style.position='relative';
      var ks=cards(col);
      if(ci===0){
        prevCenters=ks.map(function(k){return k.offsetTop+k.offsetHeight/2;});
        return;
      }
      var headH=0;var head=col.querySelector('.kr-head');
      if(head)headH=head.offsetTop; // cards start after the round header
      var centers=[];
      ks.forEach(function(k,i){
        var pa=prevCenters[i*2],pb=prevCenters[i*2+1];
        var mid;
        if(pa!=null&&pb!=null)mid=(pa+pb)/2;
        else if(pa!=null)mid=pa;
        else mid=k.offsetTop+k.offsetHeight/2;
        k.style.position='absolute';
        k.style.left='0';k.style.right='0';
        k.style.top=Math.round(mid-k.offsetHeight/2)+'px';
        centers.push(mid);
      });
      // Final column also carries the champion plinth, anchored under its match.
      var plinth=col.querySelector('.champion-plinth');
      if(plinth&&ks.length&&centers.length){
        var fk=ks[0];
        var topPx=parseFloat(fk.style.top)||0;
        plinth.style.position='absolute';
        plinth.style.left='0';plinth.style.right='0';
        plinth.style.top=Math.round(topPx+fk.offsetHeight+18)+'px';
      }
      prevCenters=centers;
    });
  }
  function drawBracket(){
    var tree=document.querySelector('.kbracket');
    if(!tree)return;
    layoutBracket();
    var svg=tree.querySelector('.bz-layer');
    if(!svg)return;
    // On narrow screens the tree is a simple stacked list — no connector layer.
    if(window.innerWidth<720){while(svg.firstChild)svg.removeChild(svg.firstChild);
      svg.setAttribute('width',0);svg.setAttribute('height',0);tree.setAttribute('data-links',0);return;}
    var cols=tree.querySelectorAll('.kr-col');
    if(cols.length<2)return;
    var box=tree.getBoundingClientRect();
    svg.setAttribute('width',tree.scrollWidth);
    svg.setAttribute('height',tree.scrollHeight);
    svg.setAttribute('viewBox','0 0 '+tree.scrollWidth+' '+tree.scrollHeight);
    while(svg.firstChild)svg.removeChild(svg.firstChild);
    var cards=[];
    cols.forEach(function(col,ci){cards[ci]=col.querySelectorAll('.km, .champion-plinth');});
    function center(el){var r=el.getBoundingClientRect();
      return {x:r.left-box.left+tree.scrollLeft,y:r.top-box.top+tree.scrollTop+r.height/2,
              left:r.left-box.left+tree.scrollLeft,right:r.right-box.left+tree.scrollLeft,h:r.height};}
    var made=0;
    for(var ci=1;ci<cards.length;ci++){
      var prev=cards[ci-1],cur=cards[ci];
      for(var i=0;i<cur.length;i++){
        var child=center(cur[i]);
        var p1=prev[i*2],p2=prev[i*2+1];
        [p1,p2].forEach(function(p){
          if(!p)return;
          var pc=center(p);
          var x1=pc.right,y1=pc.y,x2=child.left,y2=child.y;
          var mx=(x1+x2)/2;
          var d='M'+x1+' '+y1+' C'+mx+' '+y1+' '+mx+' '+y2+' '+x2+' '+y2;
          var path=document.createElementNS('http://www.w3.org/2000/svg','path');
          path.setAttribute('d',d);path.setAttribute('class','bz-link');
          path.setAttribute('fill','none');
          if(p.classList.contains('has-watched')||cur[i].classList.contains('has-watched'))
            path.setAttribute('data-watched','1');
          svg.appendChild(path);made++;
        });
      }
    }
    tree.setAttribute('data-links',made);
  }
  var rzTimer;
  function scheduleDraw(){clearTimeout(rzTimer);rzTimer=setTimeout(drawBracket,60);}


  // Entrance motion: progressive enhancement only. Content is visible by default
  // (CSS). We opt the page into a CSS-only fade-up — which always ENDS visible —
  // unless the user prefers reduced motion, in which case we leave it untouched.
  function wireReveal(){
    var mq=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)');
    if(mq&&mq.matches)return; // honor reduced motion: no entrance animation at all
    document.documentElement.classList.add('reveal-ready');
  }

  document.addEventListener('DOMContentLoaded',function(){
    apply();wireReveal();drawBracket();
  });
  window.addEventListener('load',drawBracket);
  window.addEventListener('resize',scheduleDraw);
})();
"""

STYLE = r"""
:root{
  /* palette --------------------------------------------------------------- */
  --bg:#060c0b;--bg2:#0a1512;
  --panel:rgba(16,28,25,.62);--panel2:rgba(24,40,36,.66);--panel-solid:#0e1a17;
  --line:rgba(255,255,255,.12);--line2:rgba(255,255,255,.18);--hair:rgba(255,255,255,.06);
  --text:#eaf3f0;--text-dim:#c5d6d0;--muted:#86a39b;
  --accent:#2dd4bf;--accent2:#34d399;
  --i1:#34d399;--i2:#2dd4bf;--i3:#22d3ee;--cyan:#22d3ee;
  --green:#34d399;--amber:#fbbf24;--orange:#fb923c;--rose:#fb7185;--slate:#64748b;
  --grad:linear-gradient(115deg,#34d399,#2dd4bf 55%,#22d3ee);
  --grad-soft:linear-gradient(115deg,rgba(52,211,153,.18),rgba(34,211,238,.16));
  --glow:rgba(45,212,191,.5);
  --ring:#22d3ee;                 /* deliberate focus accent (Live Wire cyan) */
  /* semantic outcome colors (paired with shape/text everywhere) */
  --c-in:#34d399;--c-bub:#fbbf24;--c-out:#475569;--c-gone:#fb7185;
  /* depth system: lit top edge + 3 elevation tiers */
  --hi:inset 0 1px 0 rgba(255,255,255,.13);
  --blur:saturate(155%) blur(20px);
  --e1:0 1px 2px rgba(0,0,0,.5),0 3px 8px -3px rgba(0,0,0,.45);
  --e2:0 4px 10px -2px rgba(0,0,0,.5),0 16px 34px -12px rgba(0,0,0,.6);
  --e3:0 12px 28px -8px rgba(0,0,0,.55),0 36px 72px -18px rgba(0,0,0,.72);
  /* type scale (fluid, ~1.2 ratio) */
  --t-3xl:clamp(2.4rem,1.5rem + 4.2vw,4.1rem);
  --t-2xl:clamp(1.8rem,1.3rem + 2.4vw,2.8rem);
  --t-xl:clamp(1.4rem,1.15rem + 1.1vw,1.85rem);
  --t-lg:clamp(1.12rem,1.02rem + .5vw,1.32rem);
  --t-md:1rem;--t-sm:.875rem;--t-xs:.76rem;--t-2xs:.68rem;
  /* spacing rhythm (8px base) */
  --s1:4px;--s2:8px;--s3:12px;--s4:16px;--s5:24px;--s6:32px;--s7:48px;--s8:64px;
  --maxw:1180px;--r:18px;--r-sm:12px;--r-lg:24px;--r-pill:999px;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--text);overflow-x:hidden;-webkit-font-smoothing:antialiased;
  font:16px/1.55 ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
a{color:inherit;text-decoration:none}
img{max-width:100%}
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);clip-path:inset(50%);white-space:nowrap;border:0;max-width:1px}
h1,h2,h3,h4{line-height:1.12;margin:0 0 .5em;letter-spacing:-.018em;font-weight:800}
h1{font-size:var(--t-2xl)}h2{font-size:var(--t-xl)}h3{font-size:var(--t-lg)}h4{font-size:var(--t-md)}
.muted{color:var(--muted);font-size:.9em}
b,strong{font-weight:700}
main{max-width:var(--maxw);margin:0 auto;padding:var(--s4) var(--s4) var(--s8);position:relative;z-index:1}

/* skip link + focus -------------------------------------------------------- */
.skip-link{position:fixed;left:var(--s3);top:-60px;z-index:100;background:var(--panel-solid);
  color:var(--text);border:1px solid var(--ring);border-radius:10px;padding:10px 16px;font-weight:700;
  box-shadow:var(--e2);transition:top .18s}
.skip-link:focus{top:var(--s3);outline:none}
:focus-visible{outline:none}
a:focus-visible,button:focus-visible,input:focus-visible,[tabindex]:focus-visible{
  outline:2px solid var(--ring);outline-offset:2px;border-radius:8px;
  box-shadow:0 0 0 4px rgba(34,211,238,.28)}
.wl-ic:focus-visible{outline:2px solid var(--ring);outline-offset:3px;border-radius:8px}

/* animated background ------------------------------------------------------ */
.bg-fx{position:fixed;inset:0;z-index:0;pointer-events:none;
  background:
    radial-gradient(42vw 42vw at 8% -10%,rgba(52,211,153,.34),transparent 60%),
    radial-gradient(38vw 38vw at 100% 4%,rgba(34,211,238,.26),transparent 60%),
    radial-gradient(48vw 48vw at 74% 112%,rgba(45,212,191,.22),transparent 60%);
  filter:saturate(1.15);animation:drift 24s ease-in-out infinite alternate}
.bg-fx::after{content:"";position:absolute;inset:0;
  background:radial-gradient(128vw 96vh at 50% 36%,transparent 50%,rgba(0,0,0,.62))}
@keyframes drift{from{transform:translate3d(0,0,0) scale(1)}to{transform:translate3d(0,-3%,0) scale(1.08)}}

/* sections + reveal -------------------------------------------------------- */
section{margin:var(--s7) 0}
section:first-of-type{margin-top:var(--s5)}
/* Entrance: a CSS-only fade-up that ALWAYS ends visible (opacity 1). Never an
   observer that could strand below-fold content if it doesn't scroll into view.
   The .reveal-ready hook (added by JS only when motion is allowed) opts a page
   into the animation; without it — JS off, or reduced motion — content is plain
   and fully visible. */
[data-reveal]{opacity:1}
.reveal-ready [data-reveal]{animation:fadeUp .6s both cubic-bezier(.2,.7,.2,1)}
.reveal-ready [data-reveal]:nth-of-type(2){animation-delay:.06s}
.reveal-ready [data-reveal]:nth-of-type(3){animation-delay:.12s}
.reveal-ready [data-reveal]:nth-of-type(4){animation-delay:.18s}
@keyframes fadeUp{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:none}}
.sec-head{display:flex;align-items:baseline;gap:var(--s3);flex-wrap:wrap;margin-bottom:var(--s4)}
.sec-head h2{margin:0;position:relative;padding-left:16px}
.sec-head h2::before{content:"";position:absolute;left:0;top:.12em;bottom:.12em;width:5px;border-radius:3px;background:var(--grad)}
.sec-head .muted{font-size:var(--t-sm)}

/* header ------------------------------------------------------------------- */
.site-head{position:sticky;top:0;z-index:30;display:flex;align-items:center;gap:18px;
  justify-content:space-between;padding:11px clamp(14px,3vw,26px);
  background:linear-gradient(180deg,rgba(7,14,12,.86),rgba(7,14,12,.66));
  backdrop-filter:var(--blur);-webkit-backdrop-filter:var(--blur);
  border-bottom:1px solid var(--line);box-shadow:0 14px 36px -20px rgba(0,0,0,.85),var(--hi)}
.brand{flex-shrink:0;min-width:0}
.brand a{display:inline-flex;align-items:center;gap:10px;font-weight:800}
.brand-wm{font-size:1.08rem;letter-spacing:-.01em}
.brand .grad{background:var(--grad);-webkit-background-clip:text;background-clip:text;color:transparent}
.brand-sub{color:var(--muted);font-weight:600;font-size:.78rem;text-transform:uppercase;letter-spacing:.14em;
  padding-left:9px;margin-left:3px;border-left:1px solid var(--line)}
.brand .ball{transition:transform .7s cubic-bezier(.2,.8,.2,1)}
.brand a:hover .ball{transform:rotate(360deg)}
.site-nav{display:flex;gap:5px}
.site-nav a{padding:8px 15px;border-radius:11px;color:var(--muted);font-weight:700;font-size:.92rem;
  transition:color .15s,background .15s;position:relative}
.site-nav a:hover{color:var(--text);background:rgba(255,255,255,.06)}
.site-nav a.on{color:#04130d;background:var(--grad);font-weight:800;box-shadow:0 8px 22px -10px var(--glow),var(--hi)}

/* Live Wire signal (shared: now-divider, bracket edge, footer dot) --------- */
.wire{position:relative}
.wire-pulse{display:inline-block;width:8px;height:8px;border-radius:50%;
  background:var(--cyan);box-shadow:0 0 0 0 rgba(34,211,238,.6);animation:wirePulse 2s ease-out infinite}
@keyframes wirePulse{0%{box-shadow:0 0 0 0 rgba(34,211,238,.55)}70%{box-shadow:0 0 0 10px rgba(34,211,238,0)}100%{box-shadow:0 0 0 0 rgba(34,211,238,0)}}

/* hero --------------------------------------------------------------------- */
.hero{position:relative;text-align:center;padding:clamp(28px,6vw,64px) 0 var(--s5)}
.hero::before{content:"";position:absolute;left:50%;top:46%;transform:translate(-50%,-50%);
  width:min(420px,72%);aspect-ratio:320/200;background:url(pitch.svg) center/contain no-repeat;
  opacity:.05;z-index:-1;pointer-events:none}
.hero-eyebrow{display:inline-flex;align-items:center;gap:9px;color:var(--text-dim);font-weight:600;
  font-size:var(--t-sm);letter-spacing:.06em;margin-bottom:var(--s4);
  padding:6px 14px;border-radius:var(--r-pill);background:var(--panel);border:1px solid var(--line);
  backdrop-filter:var(--blur);-webkit-backdrop-filter:var(--blur)}
.he-dot{width:8px;height:8px}
.hero-title{font-size:var(--t-3xl);margin:0 0 var(--s3);font-weight:800;letter-spacing:-.03em}
.grad-text{background:linear-gradient(115deg,var(--i1),var(--i2),var(--i3),var(--cyan));
  background-size:240% auto;-webkit-background-clip:text;background-clip:text;color:transparent;
  animation:sheen 9s linear infinite}
@keyframes sheen{to{background-position:240% center}}
.hero-lead{max-width:560px;margin:0 auto;color:var(--text-dim);font-size:var(--t-lg);line-height:1.5}
.hero-chips{display:flex;gap:10px;justify-content:center;flex-wrap:wrap;margin-top:var(--s5)}
.chip{display:inline-flex;align-items:center;gap:8px;padding:9px 16px;border-radius:var(--r-pill);
  background:var(--panel);border:1px solid var(--line);
  backdrop-filter:var(--blur);-webkit-backdrop-filter:var(--blur);box-shadow:var(--e1),var(--hi);font-size:.92rem}
.chip.stage b{background:var(--grad);-webkit-background-clip:text;background-clip:text;color:transparent;font-weight:800}
.chip-dot{width:8px;height:8px;border-radius:50%;background:var(--green);box-shadow:0 0 8px var(--green)}
.chip-n{font-weight:800;font-size:1.05rem;color:var(--text)}.chip-d{color:var(--muted)}

/* cards (glass) ------------------------------------------------------------ */
.card{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);
  backdrop-filter:var(--blur);-webkit-backdrop-filter:var(--blur);box-shadow:var(--e2),var(--hi)}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:var(--s5)}
.col-h{font-size:var(--t-lg)}
.match-list{display:flex;flex-direction:column;gap:9px}

/* ============ PULSE BAND (signature) ===================================== */
.pulse-section{margin-top:var(--s6)}
.pulse-head h2{margin:0}
.pulse-band{display:flex;flex-wrap:nowrap;gap:12px;overflow-x:auto;padding:6px 2px 16px;
  scroll-snap-type:x proximity;-webkit-overflow-scrolling:touch;
  mask-image:linear-gradient(90deg,transparent,#000 18px,#000 calc(100% - 18px),transparent);
  -webkit-mask-image:linear-gradient(90deg,transparent,#000 18px,#000 calc(100% - 18px),transparent)}
.pz{flex:0 0 230px;scroll-snap-align:start;background:var(--panel);border:1px solid var(--line);
  border-radius:var(--r-sm);padding:11px 13px;box-shadow:var(--e1),var(--hi);
  backdrop-filter:var(--blur);-webkit-backdrop-filter:var(--blur);transition:transform .16s,border-color .16s,box-shadow .16s}
.pz:hover{transform:translateY(-3px);border-color:var(--line2);box-shadow:var(--e2),var(--hi)}
.pz.is-upcoming{background:linear-gradient(180deg,rgba(16,28,25,.4),var(--panel))}
.pz.has-watched{border-color:var(--accent);box-shadow:var(--e2),0 0 0 1px var(--accent),0 0 26px -6px var(--glow)}
.pz-head{display:flex;align-items:center;gap:7px;font-size:var(--t-2xs);margin-bottom:9px}
.pz-grp{font-weight:800;color:var(--text-dim);text-transform:uppercase;letter-spacing:.06em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:96px}
.pz-tag{margin-left:auto;font-weight:800;letter-spacing:.04em;padding:2px 7px;border-radius:6px;font-size:.62rem}
.pz-tag.done{background:rgba(52,211,153,.16);color:#9af0c8}
.pz-tag.up{background:rgba(34,211,238,.14);color:#8fe6f3}
.pz-date{font-weight:600}
.pz-row{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:6px}
.pz-team{display:flex;align-items:center;gap:6px;min-width:0;font-weight:700;font-size:.84rem}
.pz-team:last-child{justify-content:flex-end;text-align:right}
.pz-team .fl{font-size:1.05em}
.pz-team .nm{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pz-team.watched .nm{color:var(--accent)}
.pz-score{display:flex;align-items:center;gap:2px;font-weight:800;font-size:1.05rem;font-variant-numeric:tabular-nums}
.pz-score .sg{opacity:.55}.pz-score .sg.win{opacity:1;color:var(--text)}
.pz-score .sdash{opacity:.4;margin:0 1px}
.pz-ko{font-weight:800;font-size:.92rem;color:var(--cyan);font-variant-numeric:tabular-nums;white-space:nowrap}
.pz-foot,.m-scorers{margin-top:8px;font-size:.7rem;line-height:1.5;display:flex;flex-wrap:wrap;gap:4px 8px}
.pz-foot{color:var(--muted)}
.m-scorers .scorer,.pz .scorer{color:var(--text-dim);white-space:nowrap}
.m-scorers .scorer::before,.pz .scorer::before{content:"⚽";font-size:.78em;margin-right:3px;opacity:.6}
.now-divider{flex:0 0 auto;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;
  align-self:stretch;padding:0 6px;position:relative}
.now-divider::before{content:"";position:absolute;top:8px;bottom:8px;width:2px;left:50%;transform:translateX(-50%);
  background:linear-gradient(180deg,transparent,var(--cyan),transparent);opacity:.7}
.now-divider .wire-pulse{width:11px;height:11px;z-index:1}
.now-lbl{font-size:.6rem;font-weight:900;letter-spacing:.14em;color:var(--cyan);writing-mode:vertical-rl;
  transform:rotate(180deg);z-index:1;text-shadow:0 0 10px rgba(34,211,238,.5)}

/* match line --------------------------------------------------------------- */
.match{background:var(--panel);border:1px solid var(--line);border-radius:var(--r-sm);padding:10px 14px;
  box-shadow:var(--e1),var(--hi);transition:transform .16s,border-color .16s,box-shadow .16s}
.match:hover{border-color:var(--line2);transform:translateY(-2px);box-shadow:var(--e2),var(--hi)}
.match.has-watched{border-color:var(--accent);box-shadow:var(--e2),0 0 0 1px var(--accent),0 0 24px -8px var(--glow)}
.m-meta{display:flex;gap:8px;align-items:center;font-size:.74rem;color:var(--muted);margin-bottom:6px;flex-wrap:wrap}
.m-grp{font-weight:800;color:var(--text-dim)}
.m-row{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:14px}
.m-side{display:flex;align-items:center;min-width:0}
.m-side.a{justify-content:flex-end;text-align:right}
.m-side.b{justify-content:flex-start}
.m-side .nm{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.score{display:inline-flex;align-items:center;gap:2px;font-weight:800;font-size:1.12rem;white-space:nowrap;font-variant-numeric:tabular-nums}
.score .sg{opacity:.5}.score .sg.win{opacity:1}.score .sdash{opacity:.4;margin:0 2px}
.pens{font-size:.7rem;color:var(--muted);margin-left:4px}
.vs{color:var(--cyan);font-weight:700;font-size:.82rem;white-space:nowrap;font-variant-numeric:tabular-nums}
.rd{background:rgba(255,255,255,.06);border:1px solid var(--line);border-radius:6px;padding:1px 7px;font-size:.68rem;font-weight:700}

/* team links / chips ------------------------------------------------------- */
.team,.cand,.bteam{display:inline-flex;align-items:center;gap:6px;font-weight:650;border-radius:7px;padding:1px 5px;transition:background .12s,color .12s}
.team .fl,.cand .fl,.bteam .fl{font-size:1.06em;line-height:1}
.team:hover,.cand:hover,.bteam:hover{color:#fff;background:rgba(255,255,255,.07)}
.team.watched,.cand.watched,.bteam.watched{background:rgba(45,212,191,.2);box-shadow:inset 0 0 0 1px var(--accent);font-weight:800;color:#eafff9}
.cand{font-size:.74rem;background:var(--panel2);border:1px solid var(--line);padding:2px 7px}
.cand.watched{background:rgba(45,212,191,.28)}
.slot{display:inline-flex;flex-direction:column;gap:3px}
.slot-label{color:var(--muted);font-weight:700;font-size:.84em}
.slot-cands{display:flex;flex-wrap:wrap;gap:4px}

/* tables ------------------------------------------------------------------- */
.group-card{overflow:hidden;transition:transform .16s,border-color .16s,box-shadow .16s}
.group-card:hover{transform:translateY(-3px);border-color:var(--line2);box-shadow:var(--e3),var(--hi)}
.group-card.solo{overflow-x:auto;width:100%;max-width:760px;margin:0 auto}
.group-card.solo .standings{width:100%}
.group-head{display:flex;justify-content:space-between;align-items:center;padding:12px 16px;border-bottom:1px solid var(--line);
  background:linear-gradient(180deg,rgba(255,255,255,.03),transparent)}
.group-head h3{margin:0;font-size:1.05rem}
.group-link{display:inline-flex}.group-link .arrow{color:var(--accent);transition:transform .15s;display:inline-block;margin-left:2px}
.group-link:hover{color:#fff}.group-link:hover .arrow{transform:translateX(4px)}
.group-head .muted{font-size:.78rem;font-weight:600;text-transform:uppercase;letter-spacing:.05em}
table.standings{width:100%;border-collapse:collapse;font-size:.86rem}
.standings th,.standings td{padding:8px 5px;text-align:center}
.standings th{color:var(--muted);font-weight:700;font-size:.64rem;text-transform:uppercase;letter-spacing:.06em}
.standings .tm{text-align:left;width:100%}
.group-card.solo .standings .tm{width:auto;padding-right:20px}
.standings td.pos{color:var(--muted);width:22px;font-weight:800;font-variant-numeric:tabular-nums}
.standings td.star{width:24px;padding:0}
.standings td.pts{font-weight:800;font-variant-numeric:tabular-nums}
.standings td.gd,.standings td:not(.tm):not(.st){font-variant-numeric:tabular-nums}
.standings .gd{color:var(--muted)}
.standings tbody tr{border-top:1px solid var(--hair);transition:background .12s}
.standings tbody tr:hover{background:rgba(255,255,255,.03)}
.standings tr.qual td.pos{box-shadow:inset 3px 0 0 var(--c-in)}
.standings tr.third td.pos{box-shadow:inset 3px 0 0 var(--c-bub)}
.standings tr.gone td.pos{box-shadow:inset 3px 0 0 var(--c-out)}
.standings tr.gone{opacity:.62}
.standings tr.watched{background:rgba(45,212,191,.13)}
.standings tr.watched:hover{background:rgba(45,212,191,.17)}
.standings .st{white-space:nowrap}
.r32{font-weight:700}
.badge,.th-badge{display:inline-flex;align-items:center;gap:5px;font-size:.64rem;font-weight:800;border-radius:var(--r-pill);
  padding:3px 9px;white-space:nowrap;border:1px solid transparent}
.badge .bdot{width:6px;height:6px;border-radius:50%;background:currentColor}
.badge .bcheck,.badge .bx,.badge .btri,.th-badge .bcheck,.th-badge .bx,.th-badge .btri,.th-badge .bdot{font-size:.82em;line-height:1}
.badge.win,.th-badge.win{background:rgba(52,211,153,.2);color:#7ff0c0;border-color:rgba(52,211,153,.35)}
.badge.q,.th-badge.q{background:rgba(52,211,153,.13);color:#aef3d4;border-color:rgba(52,211,153,.26)}
.badge.bub,.th-badge.bub{background:rgba(251,191,36,.16);color:var(--amber);border-color:rgba(251,191,36,.3)}
.badge.gone,.th-badge.gone{background:rgba(251,113,133,.15);color:#fda4af;border-color:rgba(251,113,133,.3)}
.th-badge.work{background:rgba(148,163,184,.16);color:#cbd5e1;border-color:rgba(148,163,184,.3)}
.group-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:var(--s4)}
.thirds td{padding:9px 6px}

/* star buttons ------------------------------------------------------------- */
.wl-ic{width:26px;height:26px;border:0;background:none;cursor:pointer;color:var(--muted);
  font-size:1.1rem;line-height:1;padding:0;transition:color .12s,transform .12s}
.wl-ic::before{content:"\2606"}
.wl-ic:hover{color:var(--amber);transform:scale(1.18)}
.wl-ic.on{color:var(--amber)}.wl-ic.on::before{content:"\2605"}
.wl{display:inline-flex;align-items:center;gap:7px;cursor:pointer;border-radius:var(--r-pill);
  border:1px solid var(--line);background:var(--panel2);color:var(--text-dim);font-weight:800;font-size:.86rem;
  padding:9px 18px;transition:border-color .15s,color .15s,background .15s}
.wl:hover{color:var(--text);border-color:var(--accent)}
.wl.on{background:linear-gradient(120deg,var(--amber),var(--orange));border-color:transparent;color:#1a1305}
.wl .wl-star{color:inherit}

/* your teams + directory --------------------------------------------------- */
.your-teams-sec{position:relative}
.tcard-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(236px,1fr));gap:12px}
.yt-grid{grid-template-columns:repeat(auto-fill,minmax(264px,1fr));gap:14px}
.tcard{position:relative;display:flex;align-items:center;gap:9px;background:var(--panel);border:1px solid var(--line);
  border-radius:14px;padding:11px 13px;box-shadow:var(--e1),var(--hi);transition:transform .16s,border-color .16s,box-shadow .16s;
  overflow:hidden}
.tcard::before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--accent);opacity:.85}
.tcard:hover{transform:translateY(-3px);border-color:var(--line2);box-shadow:var(--e3),var(--hi)}
.tcard.watched{box-shadow:0 0 0 1px var(--accent),var(--e2),0 0 28px -8px var(--glow)}
.yt-grid .tcard{padding:14px 16px}
.yt-grid .tcard::before{width:5px;background:linear-gradient(180deg,var(--accent),var(--accent2))}
.tcard-main{display:flex;align-items:center;gap:11px;flex:1;min-width:0}
.tcard-flag{font-size:1.6rem;line-height:1}
.tcard-body{display:flex;flex-direction:column;min-width:0}
.tcard-name{font-weight:800;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tcard-meta{font-size:.74rem}
.yt-empty{display:flex;align-items:center;gap:18px;padding:26px 28px;border-radius:var(--r);
  background:var(--grad-soft);border:1px dashed var(--line2);box-shadow:var(--hi)}
.yt-star{font-size:2.6rem;color:var(--amber);line-height:1;text-shadow:0 0 22px rgba(251,191,36,.45);flex:0 0 auto}
.yt-empty-body{display:flex;flex-direction:column;gap:4px}
.yt-empty-body b{font-size:1.12rem}
.directory{display:flex;flex-direction:column;gap:var(--s5)}
.dir-group .dir-head{font-weight:800;margin-bottom:10px;display:flex;align-items:baseline;gap:10px;font-size:1.05rem}
.dir-group .dir-head a:hover{color:var(--accent)}
.dir-group .dir-head .muted{font-size:.74rem;text-transform:uppercase;letter-spacing:.05em}
.search-wrap{position:relative;max-width:420px;margin-bottom:var(--s4)}
.search-ic{position:absolute;left:14px;top:50%;transform:translateY(-50%);color:var(--muted);font-size:1.1rem;pointer-events:none}
.team-search{width:100%;padding:12px 16px 12px 38px;border-radius:12px;
  border:1px solid var(--line);background:var(--panel);color:var(--text);font-size:.95rem;
  backdrop-filter:var(--blur);-webkit-backdrop-filter:var(--blur);box-shadow:var(--e1),var(--hi)}
.team-search::placeholder{color:var(--muted)}
.empty{padding:18px;border:1px solid var(--line);border-radius:12px;background:var(--panel)}
.teams-intro h1{margin-bottom:.2em}

/* ============ SCENARIO DISTRIBUTION ====================================== */
.dist-card{padding:18px 20px}
.dist-legend{display:flex;gap:18px;flex-wrap:wrap;color:var(--muted);font-size:.76rem;margin-bottom:14px;align-items:center}
.dist-legend .lg{display:inline-flex;align-items:center;gap:7px;font-weight:600}
.sw{width:13px;height:13px;border-radius:4px;display:inline-block}
.seg-in{background:var(--c-in)}.seg-bub{background:var(--c-bub)}.seg-out{background:var(--c-out)}
.dist-advh{margin-left:auto;font-weight:800;color:var(--text-dim);text-transform:uppercase;letter-spacing:.05em;font-size:.7rem}
.dist{display:flex;flex-direction:column;gap:11px}
.dist-row{display:grid;grid-template-columns:168px 1fr 58px;align-items:center;gap:14px}
.dist-row.has-watched .dist-team{font-weight:800}
.dist-row.has-watched .dist-bar{box-shadow:inset 0 0 0 1px var(--accent),inset 0 2px 6px rgba(0,0,0,.5)}
.dist-team{min-width:0;overflow:hidden}
.dist-bar{display:flex;height:26px;border-radius:8px;overflow:hidden;background:rgba(0,0,0,.4);
  box-shadow:inset 0 0 0 1px var(--line),inset 0 2px 6px rgba(0,0,0,.55)}
.dist-seg{display:flex;align-items:center;justify-content:center;min-width:0;
  transition:width .55s cubic-bezier(.3,.8,.3,1);
  box-shadow:inset 0 1px 0 rgba(255,255,255,.28),inset 0 -3px 6px rgba(0,0,0,.16)}
.dist-seg .seg-lbl{font-size:.64rem;font-weight:800;color:#08130f;letter-spacing:-.01em}
.seg-in.dist-seg{background:linear-gradient(180deg,#5be3b0,var(--c-in))}
.seg-bub.dist-seg{background:linear-gradient(180deg,#fcd362,var(--c-bub))}
.seg-out.dist-seg{background:linear-gradient(180deg,#5a6b80,var(--c-out))}
.seg-out.dist-seg .seg-lbl{color:#dde3ee}
.dist-adv{text-align:right;font-weight:800;font-size:1.02rem;font-variant-numeric:tabular-nums;color:var(--text-dim)}
.dist-adv .pct{font-size:.7em;opacity:.7;margin-left:1px}
.dist-adv.hi{color:var(--c-in)}.dist-adv.lo{color:var(--muted)}
.dist-note{margin:14px 2px 0;font-size:.8rem;line-height:1.6}
.dist-note b{font-weight:800}.k-in{color:var(--c-in)}.k-bub{color:var(--c-bub)}.k-out{color:#94a3b8}

/* ============ TEAM HERO (color takeover) ================================= */
.team-hero{position:relative;border-radius:var(--r-lg);overflow:hidden;color:#fff;
  background:linear-gradient(120deg,var(--accent),var(--accent2));
  border:1px solid rgba(255,255,255,.2);
  box-shadow:var(--e3),inset 0 1px 0 rgba(255,255,255,.34),inset 0 -50px 80px -40px rgba(0,0,0,.5)}
/* faint ball motif — non-negative offsets so it can't extend scrollWidth */
.team-hero::before{content:"";position:absolute;right:0;bottom:0;width:170px;height:170px;
  background:url(ball.svg) right -30px bottom -30px/170px 170px no-repeat;
  opacity:.12;pointer-events:none;z-index:0}
.team-hero::after{content:"";position:absolute;inset:0;pointer-events:none;z-index:0;background:
  radial-gradient(60% 130% at 100% 0,rgba(255,255,255,.3),transparent 58%),
  linear-gradient(180deg,rgba(255,255,255,.14),transparent 42%)}
.th-inner{position:relative;z-index:1;display:flex;align-items:center;gap:24px;padding:clamp(22px,4vw,34px) clamp(20px,4vw,36px);flex-wrap:wrap}
.th-flag{font-size:4.2rem;line-height:1;filter:drop-shadow(0 6px 16px rgba(0,0,0,.4))}
.th-main{flex:1;min-width:220px}
.th-eyebrow{font-size:.78rem;font-weight:700;text-transform:uppercase;letter-spacing:.14em;opacity:.86;margin-bottom:6px}
.team-hero h1{margin:0;font-size:var(--t-2xl);color:#fff;text-shadow:0 2px 18px rgba(0,0,0,.28)}
.th-line{margin:8px 0;opacity:.97;font-weight:500}
.th-grp{text-decoration:underline;text-underline-offset:3px;font-weight:700}
.th-outlook{display:flex;align-items:center;gap:12px;margin-top:12px;flex-wrap:wrap}
.th-badge{font-size:.74rem;padding:5px 12px;background:rgba(0,0,0,.28)!important;color:#fff!important;border-color:rgba(255,255,255,.36)!important}
.th-outline{font-weight:600;opacity:.95}
.th-watch{position:relative;z-index:1}
.th-watch .wl{background:rgba(0,0,0,.28);border-color:rgba(255,255,255,.5);color:#fff}
.th-watch .wl.on{background:#fff;color:#16140b;border-color:#fff}

/* group banner ------------------------------------------------------------- */
.group-banner{position:relative;overflow:hidden;display:flex;align-items:center;gap:clamp(16px,3vw,28px);
  border-radius:var(--r-lg);padding:clamp(20px,3.5vw,30px) clamp(20px,4vw,34px);
  color:#04130d;border:1px solid rgba(255,255,255,.22);background:var(--grad);
  box-shadow:var(--e3),inset 0 1px 0 rgba(255,255,255,.42),inset 0 -50px 80px -40px rgba(0,0,0,.32)}
/* ball motif — non-negative element offsets so it never extends scrollWidth */
.group-banner::before{content:"";position:absolute;right:0;top:0;width:175px;height:175px;
  background:url(ball.svg) right -34px top -34px/175px 175px no-repeat;opacity:.15;pointer-events:none}
.gb-letter{font-size:clamp(3.2rem,9vw,5rem);font-weight:900;line-height:.85;
  text-shadow:0 4px 20px rgba(0,0,0,.18);position:relative}
.gb-main{position:relative;z-index:1}
.gb-tag{font-weight:800;text-transform:uppercase;letter-spacing:.16em;font-size:.72rem;opacity:.78}
.gb-title{margin:2px 0 6px;color:#04130d;font-size:var(--t-xl)}
.gb-state{font-weight:700;opacity:.92;margin-bottom:12px}
.gb-teams{display:flex;flex-wrap:wrap;gap:7px}
.gb-teams .team{background:rgba(0,0,0,.16);color:#04130d;font-weight:700}
.gb-teams .team:hover{background:rgba(0,0,0,.28);color:#04130d}

/* ============ ROAD-TO-THE-FINAL (branch graph) =========================== */
.roads{display:grid;grid-template-columns:1fr 1fr;gap:var(--s4)}
.road-intro{margin:-6px 0 var(--s4);font-size:.86rem}
.road-line{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);padding:16px 18px;
  backdrop-filter:var(--blur);-webkit-backdrop-filter:var(--blur);box-shadow:var(--e1),var(--hi)}
.road-line.third{grid-column:1/-1}
.road-line-head{display:flex;align-items:center;gap:10px;margin-bottom:14px;flex-wrap:wrap}
.road-line-head h4{margin:0}
.road-track{font-size:.64rem;font-weight:800;text-transform:uppercase;letter-spacing:.06em;
  padding:3px 9px;border-radius:var(--r-pill);background:var(--grad);color:#04130d}
.road-track.alt{background:rgba(251,191,36,.18);color:var(--amber)}
.road-sub{margin:-6px 0 12px;font-size:.8rem}
.road-graph{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:0}
.road-step{position:relative;display:grid;grid-template-columns:88px 22px 1fr;align-items:center;gap:8px;
  padding:9px 0;min-height:46px}
.road-step+.road-step{border-top:1px dashed var(--hair)}
.road-node{display:flex;flex-direction:column;gap:2px}
.road-rd{display:inline-grid;place-items:center;min-width:42px;height:24px;padding:0 8px;border-radius:8px;
  background:var(--grad);color:#04130d;font-size:.72rem;font-weight:900;width:fit-content;
  box-shadow:0 5px 12px -5px var(--glow)}
.road-date{font-size:.66rem}
/* branch connector strokes: vertical spine + a fan elbow into the candidate set */
.road-branch{position:relative;align-self:stretch;width:22px}
.road-branch::before{content:"";position:absolute;left:50%;top:0;bottom:0;width:2px;transform:translateX(-50%);
  background:linear-gradient(180deg,transparent,var(--accent),transparent);opacity:.5}
.road-branch::after{content:"";position:absolute;left:50%;top:50%;width:11px;height:2px;background:var(--accent);opacity:.6;border-radius:2px}
.road-branch.single::before{background:var(--line);opacity:.7}
.road-step[data-cands="1"] .road-branch::after,
.road-step .road-branch.single::after{background:var(--line);opacity:.7}
.road-opp{display:flex;align-items:center;gap:9px;min-width:0;flex-wrap:wrap}
.road-vs{font-size:.62rem;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;font-weight:800}
.road-fan{display:flex;flex-wrap:wrap;gap:6px;min-width:0;position:relative}
.road-fan.multi{padding:4px 0}
.road-cand .cand{font-size:.74rem}
.road-cand.resolved .cand{background:var(--panel2);border-color:var(--line2);font-weight:800}
.road-more{display:inline-grid;place-items:center;font-size:.66rem;font-weight:800;color:var(--muted);
  border:1px dashed var(--line);border-radius:7px;padding:2px 7px}
.road-step.has-watched .road-rd{box-shadow:0 0 0 2px var(--accent),0 5px 14px -5px var(--glow)}

/* ============ BRACKET (one connected tree) =============================== */
.bracket-intro h1{margin-bottom:.2em}
/* The bracket scroll viewport is the single intentional horizontal-scroll region
   (data-hscroll): it is exactly viewport-wide and clips its wide grid child, so
   the tree never pushes the page wider than the screen — no page-level h-scroll
   on mobile (S7). */
.bracket-wrap{position:relative;width:100%;max-width:100%;overflow-x:auto;overflow-y:visible;
  -webkit-overflow-scrolling:touch}
.kbracket{position:relative;display:grid;grid-template-columns:repeat(5,minmax(170px,1fr));gap:clamp(20px,3vw,46px);
  min-width:980px;padding:6px 4px 20px}
.bz-layer{position:absolute;inset:0;z-index:0;pointer-events:none;overflow:visible}
.bz-link{stroke:var(--line2);stroke-width:1.6;opacity:.6}
.bz-link[data-watched]{stroke:var(--accent);stroke-width:2.2;opacity:.95;filter:drop-shadow(0 0 6px var(--glow))}
.kr-col{position:relative;z-index:1;display:flex;flex-direction:column;justify-content:space-around;min-width:0}
.kr-head{display:flex;align-items:center;gap:8px;font-size:.74rem;font-weight:800;text-transform:uppercase;
  letter-spacing:.08em;color:var(--text-dim);margin-bottom:14px;padding-bottom:8px;
  border-bottom:2px solid transparent;border-image:var(--grad) 1}
/* once JS positions later-round cards absolutely, keep the header at the top */
.bracket-laid .kr-col{justify-content:flex-start}
.bracket-laid .kr-head{position:sticky;top:64px;background:linear-gradient(180deg,var(--bg2),rgba(10,21,18,.4));
  backdrop-filter:var(--blur);-webkit-backdrop-filter:var(--blur);z-index:2}
.kr-count{margin-left:auto;font-size:.62rem;color:var(--muted);background:rgba(255,255,255,.06);
  border:1px solid var(--line);border-radius:var(--r-pill);padding:1px 8px}
.km{position:relative;background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:9px 11px;
  margin:8px 0;box-shadow:var(--e1),var(--hi);transition:transform .16s,border-color .16s,box-shadow .16s;
  backdrop-filter:var(--blur);-webkit-backdrop-filter:var(--blur)}
.km:hover{border-color:var(--line2);transform:translateY(-2px);box-shadow:var(--e2),var(--hi)}
.km.has-watched{border-color:var(--accent);box-shadow:var(--e2),0 0 0 1px var(--accent),0 0 26px -8px var(--glow)}
.km-live{border-color:rgba(34,211,238,.4)}
.km-no{display:flex;align-items:center;gap:6px;font-size:.62rem;color:var(--muted);margin-bottom:6px}
.km-m{font-weight:800;color:var(--text-dim)}
.km-line{position:relative;height:1px;background:var(--line);margin:6px 0}
.km-wire{position:absolute;right:-1px;top:50%;transform:translateY(-50%);opacity:0}
.km-live .km-wire{opacity:1}
.km-live .km-wire .wire-pulse{width:7px;height:7px}
.km-team{display:flex;align-items:center;gap:5px;min-width:0;font-size:.85rem;padding:1px 0}
.km-team .bteam{min-width:0;font-weight:700}
.km-team .bteam .nm{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.km-team.is-candidate{color:var(--muted)}
.km-team .bteam.prov{color:var(--text-dim);font-weight:600}
.bcode{font-size:.6rem;color:var(--muted);background:rgba(255,255,255,.05);border:1px solid var(--line);
  border-radius:5px;padding:0 5px;margin-left:3px;white-space:nowrap}
.bcands{display:inline-flex;flex-direction:column;gap:3px;min-width:0}
.bcands-list{display:flex;flex-wrap:wrap;gap:3px}
.bcands-list .cand{font-size:.66rem;padding:1px 5px}
.bslot{color:var(--muted);font-size:.78rem;font-weight:600}
.km-g{margin-left:auto;font-weight:800;font-variant-numeric:tabular-nums;min-width:16px;text-align:right}
.km-g.kloss{color:var(--muted);opacity:.7}
.km-g.kwin{color:var(--text)}
.km-team .bteam.win,.km-team:has(.kwin) .bteam{color:var(--text)}
/* Final climax: champion plinth */
.kr-final{justify-content:center}
.champion-plinth{position:relative;text-align:center;margin-top:18px;padding:22px 16px 20px;border-radius:16px;
  background:linear-gradient(180deg,rgba(251,191,36,.16),rgba(16,28,25,.7));
  border:1px solid rgba(251,191,36,.42);box-shadow:var(--e3),inset 0 1px 0 rgba(255,255,255,.18),0 0 40px -10px rgba(251,191,36,.4)}
.champion-plinth::before{content:"";position:absolute;left:50%;top:-1px;transform:translateX(-50%);width:60%;height:2px;
  background:linear-gradient(90deg,transparent,var(--amber),transparent)}
.cp-trophy{filter:drop-shadow(0 4px 14px rgba(251,191,36,.55))}
.cp-lbl{font-size:.66rem;font-weight:900;text-transform:uppercase;letter-spacing:.14em;color:var(--amber);margin:6px 0 8px}
.champ-name{display:inline-flex;align-items:center;gap:8px;font-weight:800;font-size:1.04rem}
.champ-name .fl{font-size:1.3em}
.champ-name.pending{font-weight:700;font-size:.86rem}
.champ-name.watched{color:var(--accent)}
.kr-trophy{filter:drop-shadow(0 2px 6px rgba(251,191,36,.5))}

/* footer ------------------------------------------------------------------- */
.site-foot{max-width:var(--maxw);margin:0 auto;padding:var(--s6) var(--s4) var(--s7);border-top:1px solid var(--line);
  display:flex;flex-direction:column;gap:11px;position:relative;z-index:1}
.foot-top{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:4px}
.foot-updated{display:inline-flex;align-items:center;gap:9px;font-size:.92rem;color:var(--muted)}
.foot-updated strong{color:var(--text)}
.upd-dot{display:inline-flex}.upd-dot .wire-pulse{width:8px;height:8px}
.foot-meta strong{color:var(--text)}
.foot-fine{font-size:.78rem;line-height:1.6;max-width:760px}

/* ============ RESPONSIVE ================================================= */
@media(max-width:880px){
  .roads{grid-template-columns:1fr}
}
@media(max-width:760px){
  main{padding:var(--s3) var(--s3) var(--s7)}
  section{margin:var(--s6) 0}
  .cols{grid-template-columns:1fr;gap:var(--s4)}
  .group-grid{grid-template-columns:1fr}
  .brand-sub{display:none}
  .brand-wm{font-size:.98rem}
  .site-head{gap:10px}
  .site-nav{flex-shrink:0}
  .site-nav a{padding:7px 11px;font-size:.84rem}
  .team-hero .th-inner,.group-banner{flex-direction:column;text-align:center}
  .th-outlook{justify-content:center}
  .group-banner{text-align:center;padding:20px 16px}
  .gb-main{min-width:0;max-width:100%}
  .gb-teams{justify-content:center}
  .gb-title{font-size:1.5rem}
  .standings .hide-s{display:none}
  .standings th,.standings td{padding:8px 3px}
  .dist-row{grid-template-columns:108px 1fr 46px;gap:9px}
  .road-step{grid-template-columns:72px 18px 1fr}
  .road-rd{min-width:38px;font-size:.66rem}
  .yt-empty{flex-direction:column;text-align:center;gap:10px;padding:22px}
  /* On phones let names wrap instead of ellipsis-clipping, so no element reports
     hidden horizontal overflow (S7) — multi-line names are fine here. */
  .nm,.tcard-name,.m-side .nm,.pz-team .nm{white-space:normal;overflow:visible;text-overflow:clip;word-break:break-word;min-width:0}
  .m-side{min-width:0}
  .m-side.b{justify-content:flex-start}
  .m-row{gap:8px}
  .pz-grp{max-width:none}
}
/* Mobile: the Pulse ribbon stacks into a single vertical column (still time-
   ordered, still one "now" divider) so there is NO horizontal overflow — the
   bracket tree stays the only intentional h-scroll region. */
@media(max-width:560px){
  .pulse-band{flex-wrap:wrap;overflow-x:visible;mask-image:none;-webkit-mask-image:none}
  .pz{flex:1 1 100%}
  .now-divider{flex:1 1 100%;flex-direction:row;align-self:auto;padding:4px 0;gap:10px}
  .now-divider::before{top:50%;bottom:auto;left:0;right:0;width:auto;height:2px;transform:translateY(-50%);
    background:linear-gradient(90deg,transparent,var(--cyan),transparent)}
  .now-lbl{writing-mode:horizontal-tb;transform:none}
}
@media(prefers-reduced-motion:reduce){
  *{animation:none!important;transition:none!important;scroll-behavior:auto!important}
  .bg-fx{animation:none}
  .wire-pulse{box-shadow:none}
  [data-reveal].rv{opacity:1!important;transform:none!important}
}
"""
