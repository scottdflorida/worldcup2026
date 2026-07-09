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

import hashlib
import html
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import blurbs, bracket, config, data, i18n, squads, standings, util, venues
from . import odds as odds_api
from .flags import flag
from .util import fmt_date, fmt_date_short  # noqa: F401

E = html.escape

SITE_URL = "https://worldcup.sflorida.studio"

# Frontend assets (CSS / JS / SVG artwork) live as real files under wc/assets/
# and are the single source of truth. They're loaded here at import so the
# module-level names below (STYLE, APP_JS, BALL_SVG, …) stay unchanged for
# downstream code. Per the build contract they are static — never hand-edit them
# to embed per-render data; cache-busting is handled by _asset_ver().
_ASSETS = Path(__file__).resolve().parent / "assets"


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
        self.blurbs = blurbs.load_cache()   # LLM road-to-final write-ups (may be empty)
        self.squads = squads.load_cache()   # ESPN rosters keyed by team (may be empty)
        self._wire_knockout()

    def _wire_knockout(self):
        """Once the bracket draw is set, the Round-of-32 participants ARE the teams
        that advanced — the authoritative truth (group winners, runners-up and the
        eight best thirds all in one place). Capture it, then mark every other team
        in a finished group as knocked out so badges and tables reflect reality
        without re-deriving the cross-group best-third allocation."""
        by_num = bracket.index_matches(self.matches)
        advanced = set()
        for m in self.matches:
            if m.get("round") == "Round of 32":
                for slot in (m.get("team1"), m.get("team2")):
                    res = bracket.resolve_slot(slot, self.analyses, by_num)
                    if res["team"]:
                        advanced.add(res["team"])
        self.advanced = advanced
        # The draw is "known" once enough slots resolve to real nations (24 group
        # winners + runners-up at minimum); before then we don't claim eliminations.
        self.ko_resolved = len(advanced) >= 24
        self.knocked = set()
        if not self.ko_resolved:
            return
        for info in self.analyses.values():
            if not info["complete"]:
                continue
            for t, st in info["status"].items():
                st["advanced"] = t in advanced
                if t not in advanced:
                    st["eliminated"] = True
                    self.knocked.add(t)

    def knocked_out(self, team):
        """True when a team's group is finished and it did NOT make the bracket."""
        return self.ko_resolved and team not in self.advanced and team in self.teams

    def team_fixtures(self, team):
        """(next_match, recent_match) for a team across group + knockout play,
        counting only games it is CONFIRMED in (resolved by name), newest-relevant
        first. Either may be None."""
        mine = [m for m in self.sorted_matches()
                if team in (m.get("team1"), m.get("team2"))]
        nxt = next((m for m in mine if not data.has_result(m)), None)
        recent = next((m for m in reversed(mine) if data.has_result(m)), None)
        return nxt, recent

    def next_match(self, team):
        """The team's next unplayed fixture as (match, opponent, round_label), or
        None. Falls back to the projected bracket path so a side that has advanced
        into a knockout slot still carried as a winner token (not yet named in the
        feed) still surfaces its next match — with the opponent as a live candidate
        set when it isn't decided yet."""
        nxt, _ = self.team_fixtures(team)
        by_num = bracket.index_matches(self.matches)
        if nxt is not None:
            opp_token = nxt["team2"] if nxt.get("team1") == team else nxt["team1"]
            return nxt, bracket.resolve_slot(opp_token, self.analyses, by_num), nxt.get("round", "")
        if self.knocked_out(team):
            return None
        proj = self.projections.get(team)
        if not proj:
            return None
        g = proj["group_letter"]
        entry = f'{proj["rank"]}{g}' if proj["rank"] in (1, 2) else None
        path = bracket.project_path(team, self.matches, self.analyses, g, entry) or []
        for step in path:
            m = by_num.get(step["num"])
            if m is not None and not data.has_result(m):
                return m, step["opponent"], step["round"]
        return None

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


# US Pacific is UTC-7 (PDT) for the entire tournament window (Jun 11 – Jul 19,
# 2026 are all inside US daylight time), so a fixed offset is exact here.
PT_OFFSET_HOURS = -7
PT_LABEL = "PT"


def _pt_datetime(m):
    """Fold a match's local kickoff ('13:00 UTC-6') into a single instant shifted
    to US Pacific. Returns (pt_datetime, has_clock). pt_datetime is date-only
    (midnight) when the feed carries no usable clock; None when there's no date."""
    d = m.get("date")
    if not d:
        return None, False
    try:
        base_day = datetime.strptime(d, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None, False
    t = m.get("time") or ""
    hh = mm = 0
    off = None
    has_time = False
    try:
        clock = t.split()[0]
        hh, mm = (int(x) for x in clock.split(":")[:2])
        has_time = True
    except (ValueError, IndexError):
        has_time = False
    if has_time and "UTC" in t:
        sign = -1 if "UTC-" in t else 1
        off = sign * int("".join(ch for ch in t.split("UTC")[1] if ch.isdigit()) or 0)
    if has_time and off is not None:
        utc = datetime(base_day.year, base_day.month, base_day.day, hh, mm,
                       tzinfo=timezone.utc) - timedelta(hours=off)
        return (utc + timedelta(hours=PT_OFFSET_HOURS)).replace(tzinfo=None), True
    return base_day, False


def _pt_parts(m):
    """(day, time) for display, e.g. ('Sat Jun 27', '12:00'); time None if absent."""
    pt, has_clock = _pt_datetime(m)
    if pt is None:
        return None, None
    day = f"{pt.strftime('%a %b')} {pt.day}"
    return day, (f"{pt.hour:02d}:{pt.minute:02d}" if has_clock else None)


def _utc_iso(m):
    """The match's kickoff as a UTC instant ('2026-06-27T19:00:00Z'), or None when
    the feed carries no usable clock+offset (date-only). This is the raw timestamp
    the client uses to re-render times in the viewer's chosen time zone."""
    d = m.get("date")
    if not d:
        return None
    try:
        base = datetime.strptime(d, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None
    t = m.get("time") or ""
    if "UTC" not in t:
        return None
    try:
        hh, mm = (int(x) for x in t.split()[0].split(":")[:2])
    except (ValueError, IndexError):
        return None
    sign = -1 if "UTC-" in t else 1
    off = sign * int("".join(ch for ch in t.split("UTC")[1] if ch.isdigit()) or 0)
    utc = datetime(base.year, base.month, base.day, hh, mm,
                   tzinfo=timezone.utc) - timedelta(hours=off)
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def kickoff_label(m, sep=" "):
    """Inline 'Sat Jun 27 12:00PT' with day/time spans for typographic contrast."""
    day, time = _pt_parts(m)
    if not day:
        return ""
    utc = _utc_iso(m)
    if time and utc:
        return (f'<span class="ko" data-utc="{utc}" data-tfmt="daytime">'
                f'<span class="ko-day">{E(day)}</span>{sep}'
                f'<span class="ko-time">{E(time)}<span class="ko-tz tz">{PT_LABEL}</span>'
                f'</span></span>')
    return f'<span class="ko"><span class="ko-day">{E(day)}</span></span>'


def kickoff_time_pt(m):
    """Bare Pacific clock for the focal 'score-or-time' slot, e.g. '12:00PT'."""
    _, time = _pt_parts(m)
    return f'{time}{PT_LABEL}' if time else ""


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
        return '<span class="badge gone"><span class="bx" aria-hidden="true">✕</span>Knocked out</span>'
    if st["eliminated_top2"] and not st["can_top2"]:
        return '<span class="badge bub"><span class="btri" aria-hidden="true">◆</span>3rd hope</span>'
    return ''


def group_table(info, link_header=False, solo=False, advance=None, knocked=None):
    """Render a group standings table.

    solo=True  -> standalone page (shows the qualify-status column + badges)
    link_header=True -> the group title links to its detail page (home grid)
    advance    -> if given, inject a compact advance-odds Tally cell (P reach KO),
                  so standings read as a glanceable data graphic, not a flat table.
    knocked    -> set of teams confirmed out (group finished, didn't make the
                  bracket); drives the "Knocked out" marker and drops the qualify
                  rail now that the table is settled.
    """
    letter = info["group"].split()[-1]
    show_odds = advance is not None
    knocked = knocked or set()
    rows = []
    for i, row in enumerate(info["table"], 1):
        t = row["team"]
        st = info["status"][t]
        out = t in knocked
        # status class drives the left accent rail (shape, not hue-alone, paired
        # with the badge text in solo view). Once the group is final we drop the
        # qualify rail on the top two and mark only who's knocked out.
        if out:
            cls = "gone"
        elif info["complete"]:
            cls = ""
        elif i <= 2:
            cls = "qual"
        elif i == 3:
            cls = "third"
        elif st.get("eliminated"):
            cls = "gone"
        else:
            cls = ""
        out_chip = ('<span class="ko-out" title="Knocked out">OUT</span>'
                    if out and not solo else "")
        status_cell = (f'<td class="st">{status_badge(st, info["complete"])}</td>'
                       if solo else "")
        odds_cell = ""
        if show_odds:
            adv = advance.get(t, 0) * 100
            odds_cell = (
                f'<td class="odds">'
                f'<span class="tally mini-tally" data-pct="{adv:.2f}" '
                f'title="{round(adv)}% chance to reach the knockouts">'
                f'<span class="tally-fill" style="width:{adv:.3f}%"></span>'
                f'<span class="tally-tick" style="left:50%" aria-hidden="true"></span></span>'
                f'<span class="odds-n">{round(adv)}</span></td>'
            )
        rows.append(
            f'<tr class="{cls}" data-team="{E(t)}">'
            f'<td class="pos">{i}</td>'
            f'<td class="star">{star_icon(t)}</td>'
            f'<td class="tm">{team_link(t)}{out_chip}</td>'
            f'<td>{row["P"]}</td><td>{row["W"]}</td><td>{row["D"]}</td><td>{row["L"]}</td>'
            f'<td class="hide-s">{row["GF"]}</td><td class="hide-s">{row["GA"]}</td>'
            f'<td class="gd">{row["GD"]:+d}</td><td class="pts">{row["Pts"]}</td>'
            f'{odds_cell}{status_cell}</tr>'
        )
    state = "Final" if info["complete"] else f'{info["remaining"]} to play'
    head = (f'<a class="group-link" href="group-{letter.lower()}.html"><h3>{E(info["group"])} '
            f'<span class="arrow" aria-hidden="true">→</span></h3></a>') if link_header else f'<h3>{E(info["group"])}</h3>'
    status_th = "<th>Status</th>" if solo else ""
    odds_th = '<th class="odds-h">KO&nbsp;odds</th>' if show_odds else ""
    return (
        f'<div class="card group-card{" solo" if solo else ""}{" has-odds" if show_odds else ""}">'
        f'<div class="group-head">{head}<span class="muted">{state}</span></div>'
        f'<table class="standings"><thead><tr>'
        f'<th>#</th><th aria-label="Watch"></th><th class="tm">Team</th>'
        f'<th>P</th><th>W</th><th>D</th><th>L</th>'
        f'<th class="hide-s">GF</th><th class="hide-s">GA</th><th>GD</th><th>Pts</th>{odds_th}{status_th}'
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
        # Tally threshold tick: a hard vertical ink rule at the qualification
        # boundary (the IN/BUBBLE split = the top-two line). Above it = through.
        thresh = in_pct
        advcls = "hi" if adv >= 75 else ("lo" if adv <= 20 else "")
        outcome = (f"{round(in_pct)}% qualify directly, {round(bubble_pct)}% on the third-place "
                   f"bubble, {round(out_pct)}% out — {adv}% chance to reach the knockouts")
        rows.append(
            f'<div class="dist-row" data-team="{E(t)}" title="{E(outcome)}" aria-label="{E(t)}: {E(outcome)}">'
            f'<div class="dist-team">{team_link(t)}</div>'
            f'<div class="dist-bar tally" data-thresh="{thresh:.2f}">{"".join(segs)}'
            f'<span class="tally-tick" style="left:{thresh:.3f}%" aria-hidden="true" title="qualification line"></span></div>'
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
        '<span class="lg tick"><i class="sw-tick"></i>top-two line</span>'
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


_WL = {"w": ("W", "Won"), "l": ("L", "Lost"), "d": ("D", "Drew")}


def wl_badge(code):
    """Compact result tag for a played match — solid vermilion W (won), solid
    black L (lost), black-outline D (drew). One consistent signal across the site.
    `code` is 'w' | 'l' | 'd' (or '' / None for an unplayed side -> no badge)."""
    if code not in _WL:
        return ""
    label, title = _WL[code]
    return f'<span class="wl-tag {code}" title="{title}">{label}</span>'


def side_result(done, team, winner):
    """The result code for one side of a match: 'w'/'l'/'d', or '' if unplayed.
    A played match with no winner is a draw (group stage); knockouts always
    resolve to a winner via penalties."""
    if not done:
        return ""
    if winner is None:
        return "d"
    return "w" if team == winner else "l"


def match_line(m, ctx, compact=False):
    by_num = bracket.index_matches(ctx.matches)
    t1 = bracket.resolve_slot(m["team1"], ctx.analyses, by_num)
    t2 = bracket.resolve_slot(m["team2"], ctx.analyses, by_num)
    done = data.has_result(m)
    win = bracket.match_winner(m) if done else None
    r1, r2 = side_result(done, t1["team"], win), side_result(done, t2["team"], win)
    _wcls = {"w": " won", "l": " lost", "d": " drew"}
    w1, w2 = _wcls.get(r1, ""), _wcls.get(r2, "")
    if done:
        g1, g2 = data.final_score(m)
        score = (f'<span class="score" data-live-mid><b class="sg{" win" if w1==" won" else ""}">{g1}</b>'
                 f'<span class="sdash">–</span><b class="sg{" win" if w2==" won" else ""}">{g2}</b></span>')
        pens = (m.get("score") or {}).get("p")
        if pens:
            score += f'<span class="pens">({pens[0]}–{pens[1]} pens)</span>'
    else:
        score = '<span class="vs" data-live-mid>vs</span>'
    rd = m.get("round", "")
    rd_lbl = "" if str(rd).startswith("Matchday") else f'<span class="rd">{E(rd)}</span>'
    ko = kickoff_label(m)
    meta = f'{ko} · {E(venues.venue_str(m.get("ground","")))}'
    grp = m.get("group")
    grp_lbl = f'<span class="m-grp">{E(grp)}</span>' if grp else ""
    live = bool(t1["team"] and t2["team"])
    live_attr = f' data-live data-date="{E(m.get("date",""))}"' if live else ""
    live_tag = '<span class="live-tag" data-live-tag hidden></span>' if live else ""
    b1, b2 = wl_badge(r1), wl_badge(r2)
    return (
        f'<div class="match{" is-done" if done else " is-upcoming"}"{live_attr}>'
        f'<div class="m-meta">{grp_lbl}{rd_lbl}{live_tag}<span class="muted">{meta}</span></div>'
        f'<div class="m-row"><span class="m-side a{w1}">{slot_chip(t1)}{b1}</span>{score}'
        f'<span class="m-side b{w2}">{b2}{slot_chip(t2)}</span></div>'
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
    # A tight "now" window: yesterday + today behind us, today + tomorrow ahead —
    # the pulse is about what just happened and what's next, not the whole schedule.
    today = (datetime.now(timezone.utc) + timedelta(hours=PT_OFFSET_HOURS)).date()
    yesterday, tomorrow = today - timedelta(days=1), today + timedelta(days=1)

    def pt_date(m):
        pt, _ = _pt_datetime(m)
        return pt.date() if pt is not None else None

    sm = ctx.sorted_matches()               # by (date, time): oldest->newest
    done = [m for m in sm if data.has_result(m)
            and (d := pt_date(m)) is not None and yesterday <= d <= today]
    up = [m for m in sm if not data.has_result(m)
          and (d := pt_date(m)) is not None and today <= d <= tomorrow]
    if not done and not up:
        return ""

    def card(m, kind):
        t1 = bracket.resolve_slot(m["team1"], ctx.analyses, by_num)
        t2 = bracket.resolve_slot(m["team2"], ctx.analyses, by_num)
        grp = m.get("group") or m.get("round") or ""
        venue_stadium, _ = venues.venue(m.get("ground", ""))
        pt_day, pt_time = _pt_parts(m)
        date = pt_day or ""
        utc = _utc_iso(m)
        date_attr = f' data-utc="{utc}" data-tfmt="day"' if (date and utc) else ""
        w1 = w2 = ""
        if kind == "done":
            g1, g2 = data.final_score(m)
            win = bracket.match_winner(m)
            _wc = {"w": " won", "l": " lost", "d": " drew"}
            w1 = _wc[side_result(True, t1["team"], win)]
            w2 = _wc[side_result(True, t2["team"], win)]
            pens = (m.get("score") or {}).get("p")
            pen_html = f'<span class="pz-pens">{pens[0]}–{pens[1]} pens</span>' if pens else ""
            mid = (f'<div class="pz-mid"><div class="pz-score" data-live-mid>'
                   f'<b class="sg{" win" if w1==" won" else ""}">{g1}</b><span class="sdash">–</span>'
                   f'<b class="sg{" win" if w2==" won" else ""}">{g2}</b></div>{pen_html}</div>')
            foot = scorers(m) or f'<div class="pz-foot muted">{E(venue_stadium)}</div>'
            tag = '<span class="pz-tag done" data-live-tag>FT</span>'
        else:
            ko = (f'{E(pt_time)}<span class="pz-tz tz">{PT_LABEL}</span>') if pt_time else "TBD"
            ko_attr = f' data-utc="{utc}" data-tfmt="time"' if (pt_time and utc) else ""
            mid = f'<div class="pz-ko" data-live-mid{ko_attr}>{ko}</div>'
            foot = f'<div class="pz-foot muted">{E(venue_stadium)}</div>'
            tag = '<span class="pz-tag up" data-live-tag>Kicks off</span>'
        live = bool(t1["team"] and t2["team"])
        live_attr = f' data-live data-date="{E(m.get("date",""))}"' if live else ""

        def pzteam(res, wc, is_b=False):
            t = res["team"]
            inner = (f'<span class="fl">{flag(t) if t else "·"}</span>'
                     f'<span class="nm">{E(t or res["label"])}</span>')
            badge = wl_badge({" won": "w", " lost": "l", " drew": "d"}.get(wc, ""))
            body = (badge + inner) if is_b else (inner + badge)
            if t:
                return f'<a class="pz-team{wc}" data-team="{E(t)}" href="{util.page_for(t)}">{body}</a>'
            return f'<div class="pz-team{wc}" data-team="">{body}</div>'
        return (
            f'<div class="pz {"is-done" if kind=="done" else "is-upcoming"}" '
            f'data-ts="{_epoch(m)}"{live_attr}>'
            f'<div class="pz-head"><span class="pz-grp">{E(grp)}</span>{tag}'
            f'<span class="pz-date muted"{date_attr}>{E(date)}</span></div>'
            f'<div class="pz-row">{pzteam(t1, w1)}{mid}{pzteam(t2, w2, is_b=True)}</div>'
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


def _card_opponent(ctx, m, team):
    """Resolve a team's opponent in match m to a concrete nation or candidate set."""
    by_num = bracket.index_matches(ctx.matches)
    opp_token = m["team2"] if m.get("team1") == team else m["team1"]
    return bracket.resolve_slot(opp_token, ctx.analyses, by_num)


def _opp_inline(opp, cls="tc-opp"):
    """Compact opponent for a team card: a nation, or its live candidate set."""
    if opp["team"]:
        return team_link(opp["team"], cls)
    cands = sorted(opp.get("candidates") or [])
    if 1 <= len(cands) <= 2:
        return " / ".join(team_link(c, "cand") for c in cands)
    if cands:
        return f'<span class="tc-cands">{len(cands)} possible</span>'
    return f'<span class="muted">{E(opp["label"])}</span>'


def _tcard_fixtures(ctx, team):
    """The next match (primary) and the most recent result (secondary) for a
    team — the spine of a watchlist card."""
    nm = ctx.next_match(team)
    _, recent = ctx.team_fixtures(team)
    rows = []
    if nm is not None:
        nxt, opp, rd = nm
        tag = nxt.get("group", "") if str(rd).startswith("Matchday") else _round_short(rd)
        rows.append(
            f'<div class="tc-fix tc-next">'
            f'<span class="tc-k">Next</span>'
            f'<span class="tc-line"><span class="tc-when">{kickoff_label(nxt)}</span>'
            f'<span class="tc-vs">v {_opp_inline(opp)}</span>'
            f'{f"<span class=tc-rd>{E(tag)}</span>" if tag else ""}</span></div>'
        )
    elif ctx.knocked_out(team):
        rows.append('<div class="tc-fix tc-out"><span class="tc-k out">Out</span>'
                    '<span class="tc-line muted">Knocked out of the tournament</span></div>')
    if recent is not None:
        opp = _card_opponent(ctx, recent, team)
        g1, g2 = data.final_score(recent)
        ts, os_ = (g1, g2) if recent.get("team1") == team else (g2, g1)
        res = "W" if ts > os_ else ("L" if ts < os_ else "D")
        rows.append(
            f'<div class="tc-fix tc-last">'
            f'<span class="tc-k">Last</span>'
            f'<span class="tc-line"><span class="tc-res {res.lower()}">{res} {ts}–{os_}</span>'
            f'<span class="tc-vs">v {_opp_inline(opp)}</span></span></div>'
        )
    if not rows:
        rows.append('<div class="tc-fix muted">No upcoming or recent match</div>')
    return f'<div class="tcard-fix">{"".join(rows)}</div>'


def team_card(ctx, team, rich=False):
    proj = ctx.projections[team]
    pr, sec = util.accent(team)
    rec = proj["row"]
    fixtures = _tcard_fixtures(ctx, team) if rich else ""
    return (
        f'<div class="tcard{" rich" if rich else ""}" data-team-card="{E(team)}" data-team="{E(team)}" '
        f'style="--accent:{pr};--accent2:{sec}">'
        f'<div class="tcard-top">'
        f'<a class="tcard-main" href="{util.page_for(team)}">'
        f'<span class="tcard-flag">{flag(team)}</span>'
        f'<span class="tcard-body"><span class="tcard-name">{E(team)}</span>'
        f'<span class="tcard-meta muted">{E(proj["group"])} · {_ordinal(proj["rank"])} · {rec["Pts"]} pts</span></span>'
        f'</a>{star_icon(team)}</div>'
        f'{fixtures}</div>'
    )


# --------------------------------------------------------------------------
# Shell
# --------------------------------------------------------------------------
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


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------
def page_home(ctx):
    grid = "".join(group_table(ctx.analyses[g], link_header=True, advance=ctx.advance, knocked=ctx.knocked)
                   for g in sorted(ctx.analyses))
    src = "".join(team_card(ctx, t, rich=True) for t in ctx.teams)

    resolvable = ctx.thirds_resolvable()
    # Best-third allocation race rendered as the Tally device: each team's points
    # as a fraction of the strongest third-placed side, with a hard threshold tick
    # at the 8th-best cutoff (the line eight teams must clear to advance).
    _tpts = [r["Pts"] for r in ctx.thirds]
    _tmax = max(_tpts) if _tpts else 1
    _tmax = _tmax or 1
    _cut = sorted(_tpts, reverse=True)[7] if len(_tpts) >= 8 else (min(_tpts) if _tpts else 0)
    _cut_pct = (_cut / _tmax * 100) if _tmax else 0
    thirds_rows = "".join(
        f'<tr class="{"qual" if (resolvable and _third_in(ctx, r)) else ""}" data-team="{E(r["team"])}">'
        f'<td class="pos">{r["seed"]}</td><td class="star">{star_icon(r["team"])}</td>'
        f'<td class="tm">{team_link(r["team"])}</td>'
        f'<td>{E(r["group"].split()[-1])}</td><td>{r["Pts"]}</td><td class="gd">{r["GD"]:+d}</td><td>{r["GF"]}</td>'
        f'<td class="race">'
        f'<span class="tally mini-tally" data-pct="{(r["Pts"]/_tmax*100):.2f}" title="{r["Pts"]} pts">'
        f'<span class="tally-fill" style="width:{(r["Pts"]/_tmax*100):.3f}%"></span>'
        f'<span class="tally-tick" style="left:{_cut_pct:.3f}%" aria-hidden="true" title="8th-best cutoff"></span></span></td>'
        f'<td class="r32">{(("✓ in" if _third_in(ctx, r) else "out") if resolvable else "—")}</td></tr>'
        for r in ctx.thirds
    )
    thirds_state = "resolved" if resolvable else "provisional"
    thirds_note = ("Eight third-placed teams advance to the Round of 32."
                   if resolvable else
                   "Provisional — the eight best third-placed teams are fixed once "
                   "every group finishes. This race updates as groups conclude.")
    n_played = sum(1 for m in ctx.matches if data.has_result(m))
    n_total = len(ctx.matches)
    pct_played = (n_played / n_total * 100) if n_total else 0

    body = f"""
<section class="hero" aria-label="Tournament status">
  <h1 class="hero-title">THE&nbsp;2026<br><span class="ht-big">WORLD&nbsp;CUP</span><br>IS&nbsp;<span class="ht-live">LIVE</span></h1>
  <div class="hero-foot">
    <div class="hero-prog">
      <div class="hp-head"><span class="hp-k">TOURNAMENT&nbsp;PROGRESS</span><span class="hp-pct">{round(pct_played)}<span class="hp-of">%</span></span></div>
      <div class="tally hero-tally" role="img" aria-label="{n_played} of {n_total} matches played">
        <span class="tally-fill" data-pct="{pct_played:.2f}" style="width:{pct_played:.3f}%"></span>
        <span class="tally-tick" style="left:100%" aria-hidden="true"></span>
      </div>
      <div class="hp-scale"><span>{n_played} of {n_total} matches played</span></div>
    </div>
  </div>
</section>

<section id="your-teams-sec" class="your-teams-sec" data-reveal aria-label="Your teams">
  <div class="sec-head"><h2>Your teams</h2><span class="muted">Pin any team with ★ — next &amp; latest match, lit up everywhere</span></div>
  <div id="your-teams" class="tcard-grid yt-grid"></div>
  <div id="team-src" hidden>{src}</div>
</section>

{pulse_band(ctx)}

<section class="groups-sec" data-reveal aria-label="Groups">
  <div class="sec-head"><h2>The twelve groups</h2><span class="muted">Tap a group for fixtures &amp; scenarios</span></div>
  <div class="group-grid">{grid}</div>
</section>

<section class="thirds-sec" data-reveal data-thirds-state="{thirds_state}" aria-label="Best third-placed teams">
  <div class="sec-head"><h2>Best third-placed race</h2><span class="muted">{"eight advance" if resolvable else "provisional · eight will advance"}</span></div>
  <div class="card thirds-card"><table class="standings thirds">
  <thead><tr><th>Seed</th><th aria-label="Watch"></th><th class="tm">Team</th><th>Grp</th><th>Pts</th><th>GD</th><th>GF</th><th class="race-h">Race&nbsp;to&nbsp;8th</th><th>R32</th></tr></thead>
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
  <div class="sec-head"><h2>Standings</h2><span class="muted">live table · advance odds as a tally</span></div>
  {group_table(info, solo=True, advance=ctx.advance, knocked=ctx.knocked)}
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


def squad_section(ctx, team):
    """The squad, grouped by position line, with the most recent starting XI
    highlighted. Empty string when we have no roster for this team."""
    sq = squads.squad_for(ctx.squads, team)
    if not sq or not sq.get("players"):
        return ""
    lines = []
    for code in ("G", "D", "M", "F"):
        ps = [p for p in sq["players"] if p.get("pos") == code]
        if not ps:
            continue
        items = []
        for p in ps:
            num = "" if p.get("num") in (None, "") else E(str(p["num"]))
            age = f'<span class="sq-age">{E(str(p["age"]))}</span>' if p.get("age") else ""
            st = " is-start" if p.get("starter") else ""
            items.append(
                f'<li class="sq-p{st}"><span class="sq-num">{num}</span>'
                f'<span class="sq-nm">{E(p.get("name") or "")}</span>{age}</li>')
        lines.append(
            f'<div class="sq-line"><h3 class="sq-pos">{E(squads.POS_NAME[code])}</h3>'
            f'<ul class="sq-list">{"".join(items)}</ul></div>')
    if not lines:
        return ""
    as_of = sq.get("as_of")
    cap = (f'starting XI from {E(as_of)} in <b>bold</b>' if as_of
           else "current squad by position")
    return (
        '<section aria-label="Squad">'
        f'<div class="sec-head"><h2>Squad</h2><span class="muted">{cap}</span></div>'
        f'<div class="card squad-card"><div class="squad">{"".join(lines)}</div></div>'
        '</section>')


def page_team(ctx, team):
    proj = ctx.projections[team]
    info = ctx.analyses[proj["group"]]
    pr, sec = util.accent(team)
    g = proj["group_letter"]
    ranks = set(proj["possible_ranks"])
    cur = proj["rank"]

    ko_match = bracket.find_ko_match(ctx.matches, team)
    knocked = ctx.knocked_out(team)
    roads = []
    third_html = ""
    next_ko_m = None
    if ko_match is not None:
        # The draw is set: trace the one real road forward from the confirmed slot.
        entry = f"{cur}{g}" if cur in (1, 2) else None
        roads.append(road_branch(team, g, ctx, entry, _ko_entry_heading(proj, cur),
                                 entered=True))
        # The next match to play along that road — the first round not yet
        # contested. For a team that already won a round (e.g. through to the
        # Round of 16) this is the upcoming game, even if its opponent is still
        # being decided.
        by_num = bracket.index_matches(ctx.matches)
        for step in (bracket.project_path(team, ctx.matches, ctx.analyses, g, entry) or []):
            mm = by_num.get(step["num"])
            if mm is not None and not data.has_result(mm):
                next_ko_m = mm
                break
    elif not knocked:
        # Group still in progress: show each finish's hypothetical branch.
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

    next_ko = ""
    if next_ko_m is not None:
        next_ko = (
            '<div class="next-ko" data-reveal>'
            '<div class="nk-head"><span class="nk-k">Next knockout match</span>'
            f'<span class="nk-rd">{E(_round_short(next_ko_m.get("round","")))}</span></div>'
            f'{match_line(next_ko_m, ctx)}</div>'
        )

    if roads or third_html:
        road_body = next_ko + f'<div class="roads">{"".join(roads)}{third_html}</div>'
    elif knocked:
        road_body = '<p class="muted">Knocked out — the road ends in the group stage this time.</p>'
    else:
        road_body = '<p class="muted">No knockout path yet — the bracket opens once the group stage ends.</p>'

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
  <div class="sec-head"><h2>{E(proj['group'])} standings</h2><span class="muted">your team highlighted · advance odds as a tally</span></div>
  {group_table(info, solo=True, advance=ctx.advance, knocked=ctx.knocked)}
</section>

<section aria-label="Road to the final">
  <div class="sec-head"><h2>Road to the final</h2><span class="muted">potential futures — who {E(team)} could meet each round</span></div>
  {f'<p class="road-blurb">{E(blurbs.blurb_for(ctx.blurbs, team))}</p>' if blurbs.blurb_for(ctx.blurbs, team) else ''}
  {road_body}
</section>

<section class="cols" aria-label="Fixtures">
  <div><h2 class="col-h">Results</h2><div class="match-list">{match_list(gr_played, ctx, "None yet")}</div></div>
  <div><h2 class="col-h">Remaining group games</h2><div class="match-list">{match_list(gr_upcoming, ctx, "Group complete")}</div></div>
</section>
{squad_section(ctx, team)}
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
    src = "".join(team_card(ctx, t, rich=True) for t in ctx.teams)
    body = f"""
<section class="teams-intro" aria-label="All teams">
  <h1>All 48 teams</h1>
  <p class="muted">Tap a team to inspect its path to the final; ★ to follow it across the site.</p>
</section>
<section id="your-teams-sec" class="your-teams-sec" data-reveal aria-label="Your teams">
  <div class="sec-head"><h2>Your teams</h2><span class="muted">Pin any team with ★ — next &amp; latest match, lit up everywhere</span></div>
  <div id="your-teams" class="tcard-grid yt-grid"></div>
  <div id="team-src" hidden>{src}</div>
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


_BRACKET_RAIL = [("R32", "Round of 32"), ("R16", "Round of 16"),
                 ("QF", "Quarter-final"), ("SF", "Semi-final"), ("F", "Final")]


def _km_cell(r, ci):
    """One fixed-size match box: a kickoff line and two team rows. No match
    numbers, no 'winner of M…' — unresolved sides fan to their candidate nations
    (the connectors carry the structure)."""
    sides = []
    any_candidate = False
    for key in ("team1", "team2"):
        res = r[key]
        resolved = bool(res["team"])
        if not resolved:
            any_candidate = True
        g = ""
        wl = ""
        code = side_result(r["played"], res["team"], r["winner"])
        is_win = code == "w"
        if r["played"]:
            g1, g2 = data.final_score({"score": r["score"]})
            gv = g1 if key == "team1" else g2
            g = f'<span class="km-g{" kwin" if is_win else " kloss"}">{gv}</span>'
            pens = (r["score"] or {}).get("p")
            if pens:
                pv = pens[0] if key == "team1" else pens[1]
                g += f'<span class="km-pen{" kwin" if is_win else ""}">({pv})</span>'
            # A plain W/L tag — the clearest at-a-glance read of who advanced.
            wl = wl_badge(code)
        side_cls = "km-team" + ("" if resolved else " is-candidate") + \
                   ((" kw" if is_win else " kl") if r["played"] else "")
        sides.append(f'<div class="{side_cls}">{_bracket_side(res)}{g}{wl}</div>')
    km_cls = "km" + (" km-live" if any_candidate and ci == 0 else "") + \
             (" km-done" if r["played"] else "")
    when = kickoff_label(r) or '<span class="ko"><span class="ko-day">TBD</span></span>'
    return (
        f'<div class="{km_cls}" data-mnum="{r["num"]}">'
        f'<div class="km-when">{when}</div>'
        f'{sides[0]}'
        f'<div class="km-line"><span class="km-wire wire"><span class="wire-pulse"></span></span></div>'
        f'{sides[1]}</div>'
    )


# --------------------------------------------------------------------------
# Calendar
# --------------------------------------------------------------------------
def _calendar_weeks(ctx):
    """Group every match by its Pacific calendar day, then lay the tournament out
    as full Sun→Sat weeks from the opening week through the Final's week. Returns
    a list of weeks, each a list of 7 (date, [matches]) tuples."""
    by_day = {}
    for m in ctx.matches:
        pt, _ = _pt_datetime(m)
        if pt is None:
            continue
        by_day.setdefault(pt.date(), []).append(m)
    if not by_day:
        return []
    days = sorted(by_day)
    first, last = days[0], days[-1]
    start = first - timedelta(days=(first.weekday() + 1) % 7)   # back to Sunday
    end = last + timedelta(days=(5 - last.weekday()) % 7)       # forward to Saturday
    weeks, cur = [], start
    while cur <= end:
        week = []
        for i in range(7):
            d = cur + timedelta(days=i)
            ms = sorted(by_day.get(d, []), key=lambda m: (m.get("time") or ""))
            week.append((d, ms))
        weeks.append(week)
        cur += timedelta(days=7)
    return weeks


def _cal_match(ctx, m, by_num):
    """One compact calendar entry: round/group tag, kickoff (or final score), and
    the two sides (resolved nation or live candidate pool)."""
    t1 = bracket.resolve_slot(m["team1"], ctx.analyses, by_num)
    t2 = bracket.resolve_slot(m["team2"], ctx.analyses, by_num)

    def side(res):
        if res["team"]:
            return team_link(res["team"], "cal-tm")
        cands = sorted(res.get("candidates") or [])
        if 1 <= len(cands) <= 2:
            return '<span class="cal-cands">' + "".join(team_link(c, "cal-tm cand") for c in cands) + '</span>'
        if cands:
            return f'<span class="cal-tbd">{len(cands)} possible</span>'
        return f'<span class="cal-tbd">{E(res["label"])}</span>'

    rd = m.get("round", "")
    tag = m.get("group", "") if str(rd).startswith("Matchday") else _round_short(rd)
    done = data.has_result(m)
    _, time = _pt_parts(m)
    utc = _utc_iso(m)
    t_attr = f' data-utc="{utc}" data-tfmt="time"' if (time and utc) else ""
    time_html = (f'<span class="cal-time"{t_attr}>{E(time)}<span class="cal-tz tz">PT</span></span>'
                 if time else '')
    win = bracket.match_winner(m) if done else None
    r1, r2 = side_result(done, t1["team"], win), side_result(done, t2["team"], win)
    _wc = {"w": " won", "l": " lost", "d": " drew"}
    w1, w2 = _wc.get(r1, ""), _wc.get(r2, "")
    if done:
        g1, g2 = data.final_score(m)
        pens = (m.get("score") or {}).get("p")
        pen_html = f'<span class="cal-pens">({pens[0]}–{pens[1]}p)</span>' if pens else ""
        # a calendar is about WHEN — keep the kickoff time, add the final score
        mid = f'{time_html}<span class="cal-score">{g1}–{g2}</span>{pen_html}'
    else:
        mid = (f'<span class="cal-time" data-live-mid{t_attr}>{E(time)}<span class="cal-tz tz">PT</span></span>'
               if time else '<span class="cal-time" data-live-mid>TBD</span>')
    live = bool(t1["team"] and t2["team"]) and not done
    live_attr = f' data-live data-date="{E(m.get("date",""))}"' if live else ""
    return (
        f'<div class="cal-m{" is-done" if done else ""}"{live_attr}>'
        f'<div class="cal-m-head">{f"<span class=cal-tag>{E(tag)}</span>" if tag else ""}{mid}</div>'
        f'<div class="cal-m-teams"><span class="cal-side{w1}">{side(t1)}{wl_badge(r1)}</span>'
        f'<span class="cal-v">v</span><span class="cal-side{w2}">{side(t2)}{wl_badge(r2)}</span></div>'
        f'</div>'
    )


def page_calendar(ctx):
    by_num = bracket.index_matches(ctx.matches)
    weeks = _calendar_weeks(ctx)
    today = (datetime.now(timezone.utc) + timedelta(hours=PT_OFFSET_HOURS)).date()
    dow_head = "".join(f'<div class="cal-dow-h">{d}</div>'
                       for d in ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"))
    week_html = []
    for week in weeks:
        cells = []
        for d, ms in week:
            cls = "cal-day" + (" today" if d == today else "") + (" empty" if not ms else "")
            head = (f'<div class="cal-d-head"><span class="cal-dow">{d.strftime("%a")}</span>'
                    f'<span class="cal-dom">{d.day}</span>'
                    f'<span class="cal-mon">{d.strftime("%b")}</span></div>')
            body = "".join(_cal_match(ctx, m, by_num) for m in ms)
            cells.append(f'<div class="{cls}">{head}<div class="cal-d-body">{body}</div></div>')
        week_html.append(f'<div class="cal-week">{"".join(cells)}</div>')

    body = f"""
<section class="cal-intro" aria-label="Match calendar">
  <h1>Match calendar</h1>
  <p class="muted">Every matchday in Pacific time — group stage to the Final.</p>
</section>
<div class="cal-grid" aria-label="Tournament calendar">
  <div class="cal-dow-row" aria-hidden="true">{dow_head}</div>
  {"".join(week_html)}
</div>
"""
    return shell("Match Calendar — World Cup 2026", "calendar.html", body, ctx,
                 desc="Day-by-day fixture calendar for the 2026 World Cup in Pacific time — "
                      "kickoffs, results, and the teams (or still-possible teams) for every match.",
                 page="calendar.html")


_FB_RND = {"Round of 32": "R32", "Round of 16": "R16", "Quarter-final": "QF",
           "Semi-final": "SF", "Final": "F"}


def fantasy_data(ctx):
    """The knockout tree as a pick-able structure: every match with its feeders
    (or R32 entrants) and any winner already locked by a real result. The client
    builds the picker options from this — a slot's feasible teams are its feeders'
    picked/locked occupants, or, while those are open, their whole candidate pool."""
    by_num = bracket.index_matches(ctx.matches)
    fmap = bracket.forward_map(ctx.matches)
    rev = {}
    for a, b in fmap.items():
        rev.setdefault(b, []).append(a)
    keys = bracket.tree_order_keys(ctx.matches)
    matches, order = {}, {"L": {}, "R": {}, "F": []}
    for rd in ("Round of 32", "Round of 16", "Quarter-final", "Semi-final", "Final"):
        ms = sorted([m for m in ctx.matches if m.get("round") == rd],
                    key=lambda m: keys.get(m["num"], 10 ** 9))
        rkey, half = _FB_RND[rd], len(ms) // 2
        for i, m in enumerate(ms):
            num = m["num"]
            side = "F" if rd == "Final" else ("L" if i < half else "R")
            entry = {"round": rkey, "side": side,
                     "winner": bracket.match_winner(m) if data.has_result(m) else None}
            if rd == "Round of 32":
                ents = []
                for slot in (m["team1"], m["team2"]):
                    r = bracket.resolve_slot(slot, ctx.analyses, by_num)
                    ents.append({"team": r["team"]} if r["team"]
                                else {"pool": sorted(r["candidates"])})
                entry["entrants"] = ents
            else:
                entry["feeders"] = sorted(rev.get(num, []), key=lambda n: keys.get(n, 10 ** 9))
            matches[str(num)] = entry
            (order["F"].append(num) if side == "F"
             else order[side].setdefault(rkey, []).append(num))
    teams = set()
    for e in matches.values():
        if e.get("winner"):
            teams.add(e["winner"])
        for ent in e.get("entrants", []):
            teams.update([ent["team"]] if ent.get("team") else ent.get("pool", []))
    return {"matches": matches, "order": order, "flags": {t: flag(t) for t in sorted(teams)}}


def _fb_box(num, e):
    """One winner-slot box for a match (every round, including the R32) — empty
    until the client fills it; shows the locked winner for a settled tie."""
    champ = " fb-champ" if e["round"] == "F" else ""
    locked = " fb-locked" if e.get("winner") else ""
    return (f'<div class="fb-node fb-pick fb-empty{champ}{locked}" data-m="{num}" data-round="{e["round"]}">'
            '<button class="fb-slot" type="button" aria-label="Pick winner">'
            '<span class="fb-fl"></span></button></div>')


def _fb_entrants_col(r32_nums, matches):
    """The outer flag layer: the two qualified teams that feed each R32 box, in
    tree order, so every R32 box sits midway between its pair."""
    cells = []
    for num in r32_nums:
        for ent in matches[str(num)]["entrants"]:
            if ent.get("team"):
                t = ent["team"]
                cells.append(f'<div class="fb-ent" data-r32="{num}" data-team="{E(t)}" '
                             f'title="{E(t)}"><span class="fb-fl">{flag(t)}</span></div>')
            else:  # still a candidate pool (e.g. an unresolved 3rd place)
                cells.append(f'<div class="fb-ent fb-ent-tbd" data-r32="{num}"><span class="fb-fl">·</span></div>')
    return f'<div class="fb-col fb-entrants" data-round="ENT">{"".join(cells)}</div>'


def _fb_col(rkey, nums, matches):
    cells = "".join(_fb_box(n, matches[str(n)]) for n in nums)
    return f'<div class="fb-col" data-round="{rkey}">{cells}</div>'


def _fb_upcoming(ctx, n=4):
    """A short list of the next n knockout matches still to be played, each with
    its sides (or TBD) and tz-aware kickoff — shown beneath the bracket."""
    by_num = bracket.index_matches(ctx.matches)
    ko = [m for m in ctx.matches
          if m.get("round") in ("Round of 32", "Round of 16", "Quarter-final",
                                 "Semi-final", "Final")
          and not data.has_result(m) and _utc_iso(m)]
    ko.sort(key=lambda m: _utc_iso(m) or "9999")

    def side(slot):
        r = bracket.resolve_slot(slot, ctx.analyses, by_num)
        if r["team"]:
            return f'<span class="fbu-team">{flag(r["team"])} {E(r["team"])}</span>'
        return '<span class="fbu-team tbd muted">TBD</span>'

    rows = []
    for mm in ko[:n]:
        rows.append(
            f'<li class="fbu-row">'
            f'<div class="fbu-teams">{side(mm["team1"])}<span class="fbu-v">v</span>{side(mm["team2"])}</div>'
            f'<div class="fbu-meta"><span class="fbu-rd">{_FB_RND.get(mm.get("round"), "")}</span>'
            f'<span class="fbu-when">{kickoff_label(mm)}</span></div></li>')
    if not rows:
        return ""
    return ('<section class="fbu" aria-label="Upcoming matches">'
            '<div class="sec-head"><h2>Upcoming</h2><span class="muted">next four matches</span></div>'
            f'<ul class="fbu-list">{"".join(rows)}</ul></section>')


def page_fantasy(ctx):
    fb = fantasy_data(ctx)
    m, od = fb["matches"], fb["order"]
    lr32, rr32 = od["L"].get("R32", []), od["R"].get("R32", [])
    left = (_fb_entrants_col(lr32, m)
            + "".join(_fb_col(rk, od["L"].get(rk, []), m) for rk in ("R32", "R16", "QF", "SF")))
    right = ("".join(_fb_col(rk, od["R"].get(rk, []), m) for rk in ("SF", "QF", "R16", "R32"))
             + _fb_entrants_col(rr32, m))
    final = _fb_col("F", od["F"], m)
    body = f"""
<section class="fb-intro" aria-label="Fantasy bracket">
  <div class="fb-head"><h1>Fantasy bracket</h1>
    <button id="fb-reset" class="fb-reset" type="button">Reset</button></div>
  <p class="muted">Tap to pick a winner in every undecided tie — settled results are locked. Saved on this device.</p>
</section>
<div class="fb-wrap" aria-label="Knockout bracket">
  <div class="fb">
    <svg class="fb-lines" aria-hidden="true"><path d=""/></svg>
    <div class="fb-side fb-left">{left}</div>
    {final}
    <div class="fb-side fb-right">{right}</div>
  </div>
</div>
{_fb_upcoming(ctx)}
<div class="fb-modal" id="fb-modal" hidden>
  <div class="fb-modal-back" data-fb-close></div>
  <div class="fb-modal-panel" role="dialog" aria-modal="true" aria-label="Pick the winner">
    <div class="fb-modal-head"><span class="fb-modal-k">Pick the winner</span>
      <button class="fb-modal-x" type="button" data-fb-close aria-label="Close">✕</button></div>
    <div class="fb-modal-grid" id="fb-modal-grid"></div>
    <button class="fb-modal-clear" type="button" data-fb-clear>Clear this pick</button>
  </div>
</div>
<script>window.FB_DATA={json.dumps(fb, ensure_ascii=False, separators=(",", ":"))};</script>
"""
    return shell("Fantasy Bracket — World Cup 2026", "fantasy.html", body, ctx,
                 desc="Fill in your own 2026 World Cup knockout bracket — a compact, flags-only "
                      "picker where every undecided tie is yours to call.",
                 page="fantasy.html")


# --------------------------------------------------------------------------
# Betting pool — knockout match odds (model-derived) served to the backend
# --------------------------------------------------------------------------
def _team_ratings(ctx):
    """A rough strength number per team from its group-stage form — the spine of
    the model odds. (Swap in a public odds feed later; the backend just reads
    odds1/odds2 from bets-data.json.)"""
    r = {}
    for info in ctx.analyses.values():
        for row in info["table"]:
            r[row["team"]] = row["Pts"] + 0.35 * row["GD"] + 0.08 * row["GF"]
    return r


def _odds_pair(ra, rb):
    """Two decimal prices from a rating gap, with a small bookmaker margin."""
    import math
    pa = 1.0 / (1.0 + math.exp(-(ra - rb) / 3.0))
    pa = min(max(pa, 0.08), 0.92)
    return (round(max(1.05, (1.0 / pa) * 0.93), 2),
            round(max(1.05, (1.0 / (1.0 - pa)) * 0.93), 2))


def betting_data(ctx):
    """Every knockout match whose two sides are known: the matchup, model odds,
    kickoff, and result. The Pages Functions read this to list bettable games,
    snapshot odds onto a wager, and settle once a match is decided."""
    by_num = bracket.index_matches(ctx.matches)
    ratings = _team_ratings(ctx)
    cache = odds_api.load_cache()      # public market odds, when available
    out = []
    for m in ctx.matches:
        if m.get("round") not in ("Round of 32", "Round of 16", "Quarter-final",
                                  "Semi-final", "Final"):
            continue
        t1 = bracket.resolve_slot(m["team1"], ctx.analyses, by_num)
        t2 = bracket.resolve_slot(m["team2"], ctx.analyses, by_num)
        if not (t1["team"] and t2["team"]):
            continue  # not bettable until both sides are set
        pub = odds_api.pair_odds(cache, t1["team"], t2["team"])
        if pub:
            (o1, o2), src = pub, "live"
        else:
            o1, o2 = _odds_pair(ratings.get(t1["team"], 3), ratings.get(t2["team"], 3))
            src = "model"
        out.append({
            "num": m["num"], "round": _FB_RND.get(m.get("round"), m.get("round")),
            "team1": t1["team"], "team2": t2["team"], "odds1": o1, "odds2": o2,
            "oddsSrc": src, "kickoff": _utc_iso(m), "decided": data.has_result(m),
            "winner": bracket.match_winner(m) if data.has_result(m) else None,
        })
    teams = sorted({x for m in out for x in (m["team1"], m["team2"])})
    return {"matches": out, "flags": {t: flag(t) for t in teams},
            "urls": {t: util.page_for(t) for t in teams}, "stage": ctx.stage()}


def page_betting(ctx):
    body = """
<section class="bet-intro" aria-label="Betting pool">
  <div class="fb-head"><h1>Betting pool</h1></div>
  <p class="muted">Play money. Everyone starts with $100, bet any amount on who wins each
  knockout match, payouts at the listed odds. Hit $0 and you're out.</p>
</section>
<div id="bet-app" class="bet-app" aria-live="polite">
  <p class="muted bet-loading">Loading…</p>
</div>
<div class="fb-modal" id="bet-modal" hidden>
  <div class="fb-modal-back" data-bet-close></div>
  <div class="fb-modal-panel" role="dialog" aria-modal="true" aria-label="Place a bet">
    <div class="fb-modal-head"><span class="fb-modal-k" id="bet-modal-k">Place a bet</span>
      <button class="fb-modal-x" type="button" data-bet-close aria-label="Close">✕</button></div>
    <div class="bet-form" id="bet-form"></div>
  </div>
</div>
"""
    return shell("Betting Pool — World Cup 2026", "betting.html", body, ctx,
                 desc="A play-money World Cup knockout betting pool with friends — $100 to "
                      "start, bet on match winners at model odds, and climb the leaderboard.",
                 page="betting.html")


def page_bracket(ctx):
    rounds = [(rd, rows) for rd, rows in ctx.bracket if rd != "Match for third place"]
    n_round = len(rounds)
    cols = []
    for ci, (rd, rows) in enumerate(rounds):
        is_final = rd == "Final"
        cells = "".join(_km_cell(r, ci) for r in rows)
        if is_final:
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
                f'<div class="kr-body">{cells}{plinth}</div></div>'
            )
        else:
            cols.append(
                f'<div class="kr-col"><div class="kr-head">{E(rd)} '
                f'<span class="kr-count">{len(rows)}</span></div>'
                f'<div class="kr-body">{cells}</div></div>'
            )

    stage = ctx.stage()
    active = next((i for i, (_, key) in enumerate(_BRACKET_RAIL) if key == stage), 0)
    rail_items = "".join(
        f'<span class="brn-item{" on" if i == active else ""}" data-rd="{i}">{E(short)}</span>'
        for i, (short, _) in enumerate(_BRACKET_RAIL))

    body = f"""
<section class="bracket-intro" aria-label="Knockout bracket">
  <h1>Knockout bracket</h1>
  <p class="muted">Round of 32 → Final as one connected tree. Pin teams with ★ to mark their path.</p>
  <div class="bracket-rail" aria-label="Bracket rounds">
    <span class="brn-label">Current round:</span>
    <div class="bracket-rail-nav">{rail_items}</div>
  </div>
</section>
<div class="bracket-frame at-start" data-bracket>
  <span class="bz-edge-l" aria-hidden="true"></span>
  <span class="bz-edge-r" aria-hidden="true"></span>
  <div class="bracket-wrap" data-hscroll>
    <div class="kbracket" data-rounds="{n_round}">
      <svg class="bz-layer" aria-hidden="true"></svg>
      {"".join(cols)}
    </div>
  </div>
</div>
"""
    return shell("Knockout Bracket — World Cup 2026", "bracket.html", body, ctx,
                 desc="The full 2026 World Cup knockout bracket as one connected tree, "
                      "Round of 32 to the Final — with live candidates before slots resolve "
                      "and your pinned teams glowing through.",
                 page="bracket.html")


def _bracket_side(res):
    """A bracket slot: a resolved nation, or the set of teams that could fill it.

    Never shows 'Winner of M…'. Two or fewer candidates read as named chips; more
    collapse to a flags row (names hidden via CSS). The box grows to show them all."""
    if res["team"]:
        return team_link(res["team"], "bteam")
    prov = res.get("provisional")
    if prov:  # group still in progress: show who currently holds the slot
        return (f'{team_link(prov, "bteam prov")}'
                f'<span class="bcode" title="current table position">{E(res.get("slot",""))}</span>')
    cands = sorted(res.get("candidates") or [])
    if not cands:
        return '<span class="bslot muted">TBD</span>'
    chips = "".join(team_link(c, "bcand") for c in cands)
    cls = "bcands" + (" many" if len(cands) > 2 else "")
    return f'<span class="{cls}" data-n="{len(cands)}">{chips}</span>'


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
        date = kickoff_label({"date": s.get("date"), "time": s.get("time")})
        if s.get("played"):
            # A round already contested: show the result + score, not a fan of
            # hypothetical opponents.
            won = s.get("won")
            opp_chip = (team_link(opp["team"], "cand") if opp["team"]
                        else f'<span class="road-cand tbd muted">{E(opp["label"])}</span>')
            pens = (f'<span class="road-score pens">({E(s["pens"])} pens)</span>'
                    if s.get("pens") else "")
            mark = "✓" if won else "✕"
            res = "won" if won else "lost"
            steps.append(
                f'<li class="road-step done {res}" data-cands="1">'
                f'<div class="road-node"><span class="road-rd">{E(rd_short)}</span>'
                f'<span class="road-date muted">{date}</span></div>'
                f'<span class="road-branch single" aria-hidden="true"></span>'
                f'<div class="road-opp"><span class="road-rmark {res}" aria-hidden="true">{mark}</span>'
                f'{opp_chip}<span class="road-score">{E(s.get("score",""))}</span>{pens}</div>'
                f'</li>'
            )
            continue
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
            f'<span class="road-date muted">{date}</span></div>'
            f'{branch}'
            f'<div class="road-opp"><span class="road-vs">vs</span>{fan}</div>'
            f'</li>'
        )
    ended_loss = bool(path and path[-1].get("played") and not path[-1].get("won"))
    if ended_loss:
        tag = '<span class="road-track out">Knocked out</span>'
    elif entered:
        tag = '<span class="road-track">current track</span>'
    else:
        tag = ''
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
        date = kickoff_label(m)
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
            f'<span class="road-date muted">{date}</span></div>'
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


def _third_in(ctx, r):
    """Whether a third-placed team made the Round of 32 — the actual bracket
    participants once the draw is set, else the provisional points ranking."""
    if getattr(ctx, "ko_resolved", False):
        return r["team"] in ctx.advanced
    return r["qualifies"]


def _round_short(rd):
    return {"Round of 32": "R32", "Round of 16": "R16", "Quarter-final": "QF",
            "Semi-final": "SF", "Final": "Final"}.get(rd, rd)


def _ko_entry_heading(proj, cur):
    """Headline for a team's confirmed knockout road (how it entered the bracket)."""
    g = proj["group"]
    if cur == 1:
        return f"{g} winners"
    if cur == 2:
        return f"{g} runners-up"
    return "Through as a best third"


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
    # Fresh asset fingerprint for THIS render (memoized across every shell()
    # call below); recomputed here so it reflects the current i18n.js bytes.
    global _asset_ver_cache
    _asset_ver_cache = None
    ctx = Context(payload)
    files = {
        "index.html": page_home(ctx),
        "teams.html": page_teams(ctx),
        "bracket.html": page_bracket(ctx),
        "fantasy.html": page_fantasy(ctx),
        "betting.html": page_betting(ctx),
        "bets-data.json": json.dumps(betting_data(ctx), ensure_ascii=False, separators=(",", ":")),
        "calendar.html": page_calendar(ctx),
        "assets/style.css": STYLE,
        "assets/app.js": APP_JS,
        "assets/i18n.js": i18n.build_js(),
        "assets/ball.svg": BALL_SVG,
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
