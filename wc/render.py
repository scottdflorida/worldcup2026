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

from . import blurbs, bracket, config, data, standings, util, venues
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
        self.blurbs = blurbs.load_cache()   # LLM road-to-final write-ups (may be empty)
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


def match_line(m, ctx, compact=False):
    by_num = bracket.index_matches(ctx.matches)
    t1 = bracket.resolve_slot(m["team1"], ctx.analyses, by_num)
    t2 = bracket.resolve_slot(m["team2"], ctx.analyses, by_num)
    done = data.has_result(m)
    if done:
        g1, g2 = data.final_score(m)
        cls1 = " win" if g1 > g2 else ""
        cls2 = " win" if g2 > g1 else ""
        score = (f'<span class="score" data-live-mid><b class="sg{cls1}">{g1}</b>'
                 f'<span class="sdash">–</span><b class="sg{cls2}">{g2}</b></span>')
        pens = (m.get("score") or {}).get("p")
        if pens:
            score += f'<span class="pens">({pens[0]}–{pens[1]}p)</span>'
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
    return (
        f'<div class="match{" is-done" if done else " is-upcoming"}"{live_attr}>'
        f'<div class="m-meta">{grp_lbl}{rd_lbl}{live_tag}<span class="muted">{meta}</span></div>'
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
        if kind == "done":
            g1, g2 = data.final_score(m)
            cls1 = " win" if g1 > g2 else ""
            cls2 = " win" if g2 > g1 else ""
            mid = (f'<div class="pz-score" data-live-mid><b class="sg{cls1}">{g1}</b>'
                   f'<span class="sdash">–</span><b class="sg{cls2}">{g2}</b></div>')
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
        return (
            f'<div class="pz {"is-done" if kind=="done" else "is-upcoming"}" '
            f'data-ts="{_epoch(m)}"{live_attr}>'
            f'<div class="pz-head"><span class="pz-grp">{E(grp)}</span>{tag}'
            f'<span class="pz-date muted"{date_attr}>{E(date)}</span></div>'
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
    ("calendar.html", "Calendar"),
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
<meta name="theme-color" content="#F4F2EC">
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
<link rel="stylesheet" href="assets/style.css?v={ASSET_VER}">
<script>window.WC_DEFAULT_WATCH={json.dumps(config.DEFAULT_WATCH)};</script>
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>
<header class="site-head">
  <div class="brand"><a href="index.html" aria-label="World Cup 2026 tracker — home">
    <span class="wm-mark" aria-hidden="true"><svg viewBox="0 0 36 36" width="30" height="30"><rect width="36" height="36" rx="3" fill="var(--ink)"/><text x="18" y="25" text-anchor="middle" font-family="ui-monospace,Menlo,monospace" font-weight="800" font-size="17" letter-spacing="-1" fill="var(--accent)">26</text></svg></span>
    <span class="wm-text"><span class="wm-l1">WORLD&nbsp;CUP</span><span class="wm-l2">TRACKER&nbsp;<span class="wm-yr">/26</span></span></span></a></div>
  <nav class="site-nav" aria-label="Primary">{nav}</nav>
</header>
<main id="main">
{body}
</main>
<footer class="site-foot">
  <div class="foot-rule" aria-hidden="true"></div>
  <div class="foot-grid">
    <div class="foot-cell foot-brand">
      <span class="foot-wm">WORLD&nbsp;CUP&nbsp;<span class="foot-yr">/26</span></span>
      <span class="foot-sub">Live match-center · {E(config.TOURNAMENT["hosts"])}</span>
    </div>
    <div class="foot-cell foot-stat">
      <span class="foot-k">STAGE</span><span class="foot-v">{E(ctx.stage())}</span>
    </div>
    <div class="foot-cell foot-stat">
      <span class="foot-k">UPDATED</span>
      <span class="foot-v"><span class="upd-dot wire" aria-hidden="true"><span class="wire-pulse"></span></span>{E(updated) or "—"}</span>
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
<script src="assets/app.js?v={ASSET_VER}"></script>
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
    if ko_match is not None:
        # The draw is set: trace the one real road forward from the confirmed slot.
        entry = f"{cur}{g}" if cur in (1, 2) else None
        roads.append(road_branch(team, g, ctx, entry, _ko_entry_heading(proj, cur),
                                 entered=True))
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
    if ko_match is not None and not data.has_result(ko_match):
        next_ko = (
            '<div class="next-ko" data-reveal>'
            '<div class="nk-head"><span class="nk-k">Next knockout match</span>'
            f'<span class="nk-rd">{E(_round_short(ko_match.get("round","")))}</span></div>'
            f'{match_line(ko_match, ctx)}</div>'
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
        if r["played"]:
            g1, g2 = data.final_score({"score": r["score"]})
            gv = g1 if key == "team1" else g2
            winner = r["winner"]
            is_win = bool(winner and res["team"] == winner)
            g = f'<span class="km-g{" kwin" if is_win else " kloss"}">{gv}</span>'
        side_cls = "km-team" + ("" if resolved else " is-candidate")
        sides.append(f'<div class="{side_cls}">{_bracket_side(res)}{g}</div>')
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
    if done:
        g1, g2 = data.final_score(m)
        # a calendar is about WHEN — keep the kickoff time, add the final score
        mid = f'{time_html}<span class="cal-score">{g1}–{g2}</span>'
    else:
        mid = (f'<span class="cal-time" data-live-mid{t_attr}>{E(time)}<span class="cal-tz tz">PT</span></span>'
               if time else '<span class="cal-time" data-live-mid>TBD</span>')
    live = bool(t1["team"] and t2["team"]) and not done
    live_attr = f' data-live data-date="{E(m.get("date",""))}"' if live else ""
    return (
        f'<div class="cal-m{" is-done" if done else ""}"{live_attr}>'
        f'<div class="cal-m-head">{f"<span class=cal-tag>{E(tag)}</span>" if tag else ""}{mid}</div>'
        f'<div class="cal-m-teams"><span class="cal-side">{side(t1)}</span>'
        f'<span class="cal-v">v</span><span class="cal-side">{side(t2)}</span></div>'
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
    ctx = Context(payload)
    files = {
        "index.html": page_home(ctx),
        "teams.html": page_teams(ctx),
        "bracket.html": page_bracket(ctx),
        "calendar.html": page_calendar(ctx),
        "assets/style.css": STYLE,
        "assets/app.js": APP_JS,
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
# Ball mark: original ink-line ball on paper (broadcast-ink palette, no trademarks).
BALL_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" fill="none">
<circle cx="32" cy="32" r="30" fill="#F4F2EC" stroke="#13110D" stroke-width="2.6"/>
<polygon points="32,23 40.56,29.22 37.29,39.28 26.71,39.28 23.44,29.22" fill="#13110D"/>
<g stroke="#13110D" stroke-width="2.3" stroke-linecap="round">
<line x1="32" y1="23" x2="32" y2="3.5"/>
<line x1="40.56" y1="29.22" x2="59" y2="23"/>
<line x1="37.29" y1="39.28" x2="48.6" y2="55"/>
<line x1="26.71" y1="39.28" x2="15.4" y2="55"/>
<line x1="23.44" y1="29.22" x2="5" y2="23"/>
</g></svg>"""

# Trophy mark: a flat ink cup with a single vermilion star — original, no FIFA art.
TROPHY_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" fill="none">
<g fill="#13110D" stroke="#13110D" stroke-width="1.1" stroke-linejoin="round">
<path d="M13 7 H35 V14 A11 11 0 0 1 13 14 Z"/>
<path d="M13 9 H7.5 a4.5 5.5 0 0 0 7 9.2" fill="none" stroke-width="2"/>
<path d="M35 9 H40.5 a4.5 5.5 0 0 1 -7 9.2" fill="none" stroke-width="2"/>
<rect x="22" y="24" width="4" height="7"/>
<rect x="15.5" y="31" width="17" height="4.2" rx="1"/>
<rect x="13" y="35" width="22" height="4.4" rx="1"/>
</g>
<path d="M24 9.2 l1.6 3.4 3.7.4 -2.8 2.5 .8 3.7 -3.3-1.9 -3.3 1.9 .8-3.7 -2.8-2.5 3.7-.4 Z" fill="#FF3B14"/>
</svg>"""

# Favicon: an original mono "26" lockup — ink tile, vermilion numerals, hard edge.
FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect width="64" height="64" rx="9" fill="#13110D"/>
<rect x="8" y="8" width="48" height="48" rx="4" fill="none" stroke="#F4F2EC" stroke-width="2" opacity=".22"/>
<rect x="8" y="8" width="8" height="48" rx="4" fill="#FF3B14"/>
<text x="36" y="43" text-anchor="middle" font-family="ui-monospace,Menlo,Consolas,monospace" font-weight="800"
  font-size="27" fill="#F4F2EC" letter-spacing="-2">26</text>
</svg>"""

# OG card (1200x630) — broadsheet "Broadcast Ink" identity: paper ground, ink type,
# one vermilion block. Original art, no FIFA/World Cup trademarks.
OG_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 630">
<rect width="1200" height="630" fill="#F4F2EC"/>
<g stroke="#13110D" stroke-width="1" opacity=".07">
<line x1="0" y1="118" x2="1200" y2="118"/><line x1="0" y1="512" x2="1200" y2="512"/>
<line x1="80" y1="0" x2="80" y2="630"/><line x1="1120" y1="0" x2="1120" y2="630"/>
</g>
<g transform="translate(80,52)">
<rect width="46" height="46" rx="4" fill="#13110D"/>
<rect width="9" height="46" rx="4" fill="#FF3B14"/>
<text x="29" y="33" text-anchor="middle" font-family="ui-monospace,Menlo,monospace" font-weight="800" font-size="22" fill="#F4F2EC" letter-spacing="-1">26</text>
<text x="68" y="20" font-family="ui-monospace,Menlo,monospace" font-weight="700" font-size="18" fill="#13110D" letter-spacing="4">WORLD CUP TRACKER</text>
<text x="68" y="44" font-family="ui-monospace,Menlo,monospace" font-weight="600" font-size="14" fill="#6A6458" letter-spacing="4">LIVE MATCH-CENTER · USA · CAN · MEX</text>
</g>
<text x="76" y="290" font-family="Helvetica,Arial,sans-serif" font-weight="800" font-size="152" fill="#13110D" letter-spacing="-6">THE WORLD</text>
<text x="76" y="430" font-family="Helvetica,Arial,sans-serif" font-weight="800" font-size="152" fill="#13110D" letter-spacing="-6">CUP IS <tspan fill="#FF3B14">LIVE</tspan></text>
<g transform="translate(80,556)" font-family="ui-monospace,Menlo,monospace" font-weight="700" font-size="17" letter-spacing="2">
<rect x="0" y="-18" width="10" height="22" fill="#FF3B14"/>
<text x="22" y="0" fill="#13110D">STANDINGS · ADVANCE ODDS · EVERY ROAD TO THE FINAL</text>
</g>
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
        host.innerHTML='<div class="yt-empty">'+
          '<span class="yt-star" aria-hidden="true">★</span>'+
          '<div class="yt-empty-body">'+
          '<span class="yt-k">EMPTY&nbsp;WATCHLIST</span>'+
          '<b class="yt-h">PIN A TEAM.</b>'+
          '<span class="yt-p">Tap the <span class="yt-inline">★</span> beside any nation — on a group, a team page, or the bracket — '+
          'and it locks in here, marked in vermilion across the whole site.</span>'+
          '<span class="yt-cta"><a href="teams.html">Browse all 48 teams →</a></span>'+
          '</div></div>';
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
    document.querySelectorAll('.match,.km,.dist-row,.pz,.road-step,.tcard,.cal-m').forEach(function(el){
      el.classList.toggle('has-watched',!!el.querySelector('.watched'));
    });
    document.querySelectorAll('[data-watch]').forEach(function(btn){
      var on=w.indexOf(btn.getAttribute('data-watch'))>=0;
      btn.classList.toggle('on',on);btn.setAttribute('aria-pressed',on?'true':'false');
      var lab=btn.querySelector('.wl-txt');if(lab)lab.textContent=on?'Watching':'Watch';
    });
    if(document.querySelector('.kbracket'))scheduleDraw();  // recolor watched strokes
    applyTZ();  // re-render times (incl. the freshly cloned Your-teams cards)
  }
  // ---- time zone: re-render every [data-utc] time in the viewer's chosen zone ----
  var TZS={'America/New_York':'ET','America/Chicago':'CT','America/Denver':'MT',
           'America/Los_Angeles':'PT','America/Sao_Paulo':'BRT'};
  var TZ_KEY='wc26.tz', TZ_DEFAULT='America/Los_Angeles';
  function getTZ(){try{var v=localStorage.getItem(TZ_KEY);if(v&&TZS[v])return v;}catch(e){}return TZ_DEFAULT;}
  function setTZ(v){try{localStorage.setItem(TZ_KEY,v);}catch(e){}}
  function tzParts(utc,tz){
    var d=new Date(utc);
    if(isNaN(d))return null;
    var day=new Intl.DateTimeFormat('en-US',{timeZone:tz,weekday:'short',month:'short',day:'numeric'}).format(d).replace(/,/g,'');
    var time=new Intl.DateTimeFormat('en-US',{timeZone:tz,hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(d);
    return {day:day,time:time};
  }
  function applyTZ(){
    var tz=getTZ(), label=TZS[tz]||'';
    document.querySelectorAll('[data-utc]').forEach(function(el){
      if(el.classList.contains('live-mid'))return;          // currently showing a live score
      var p=tzParts(el.getAttribute('data-utc'),tz); if(!p)return;
      var fmt=el.getAttribute('data-tfmt');
      if(fmt==='day'){el.textContent=p.day;return;}
      if(fmt==='daytime'){
        var dy=el.querySelector('.ko-day'); if(dy)dy.textContent=p.day;
        var tm=el.querySelector('.ko-time');
        if(tm){var c=(tm.querySelector('.tz')||{}).className||'ko-tz tz';
          tm.innerHTML=p.time+'<span class="'+c+'">'+label+'</span>';}
        return;
      }
      var cc=(el.querySelector('.tz')||{}).className||'tz';   // 'time'
      el.innerHTML=p.time+'<span class="'+cc+'">'+label+'</span>';
    });
  }
  function wireTZ(){
    var sel=document.getElementById('tz-select'); if(!sel)return;
    sel.value=getTZ();
    sel.addEventListener('change',function(){setTZ(sel.value);applyTZ();});
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

  // ---- Bracket layout + connectors. Boxes size to their content (a deep round
  // can hold many candidate flags), so we can't rely on CSS alone for vertical
  // centering. We lay the Round-of-32 leaves on an even grid, then place every
  // later box at the midpoint of its two feeders' centres (works for ANY box
  // height), drop the champion plinth right under the final, and draw the
  // right-angle strokes. Progressive enhancement: with JS off the columns just
  // stack top-aligned (still legible); narrow screens use the stacked fallback.
  function updateEdges(){
    var frame=document.querySelector('[data-bracket]');
    var wrap=frame&&frame.querySelector('.bracket-wrap');
    if(!frame||!wrap)return;
    var max=wrap.scrollWidth-wrap.clientWidth;
    frame.classList.toggle('at-start',wrap.scrollLeft<=1);
    frame.classList.toggle('at-end',max<=1||wrap.scrollLeft>=max-1);
  }
  function layoutBracket(){
    var tree=document.querySelector('.kbracket');
    if(!tree)return 0;
    var cols=[].slice.call(tree.querySelectorAll('.kr-col'));
    if(!cols.length)return 0;
    function body(col){return col.querySelector('.kr-body')||col;}
    function cards(col){return [].slice.call(body(col).querySelectorAll('.km'));}
    // Reset prior positioning so heights measure naturally.
    cols.forEach(function(col){
      cards(col).forEach(function(k){k.style.position='';k.style.top='';k.style.left='';k.style.right='';});
      var pl=col.querySelector('.champion-plinth');
      if(pl){pl.style.position='';pl.style.top='';pl.style.left='';pl.style.right='';}
      body(col).style.height='';
    });

    var leaves=cards(cols[0]);
    if(!leaves.length)return 0;
    var maxLeafH=0;leaves.forEach(function(k){maxLeafH=Math.max(maxLeafH,k.offsetHeight);});
    var slot=maxLeafH+28;                       // even vertical pitch for the leaves
    var bodyH=leaves.length*slot;
    var prev=null;
    cols.forEach(function(col,ci){
      var b=body(col);b.style.position='relative';b.style.height=bodyH+'px';
      var ks=cards(col),centers=[];
      ks.forEach(function(k,i){
        var c;
        if(ci===0){c=(i+0.5)*slot;}
        else{var a=prev[i*2],z=prev[i*2+1];
          c=(a!=null&&z!=null)?(a+z)/2:(a!=null?a:(z!=null?z:(i+0.5)*slot));}
        k.style.position='absolute';k.style.left='0';k.style.right='0';
        k.style.top=Math.round(c-k.offsetHeight/2)+'px';
        centers.push(c);
      });
      var plinth=col.querySelector('.champion-plinth');
      if(plinth&&ks.length){
        var fb=ks[ks.length-1];
        plinth.style.position='absolute';plinth.style.left='0';plinth.style.right='0';
        plinth.style.top=Math.round((parseFloat(fb.style.top)||0)+fb.offsetHeight+16)+'px';
      }
      prev=centers;
    });
    return bodyH;
  }
  function drawBracket(){
    var tree=document.querySelector('.kbracket');
    if(!tree)return;
    layoutBracket();
    updateEdges();
    var svg=tree.querySelector('.bz-layer');
    if(!svg)return;
    while(svg.firstChild)svg.removeChild(svg.firstChild);
    var cols=[].slice.call(tree.querySelectorAll('.kr-col'));
    if(cols.length<2)return;
    var W=tree.scrollWidth,H=tree.scrollHeight;
    svg.setAttribute('width',W);svg.setAttribute('height',H);
    svg.setAttribute('viewBox','0 0 '+W+' '+H);
    var kb=tree.getBoundingClientRect();
    // km positions are scroll-invariant relative to .kbracket (both move with the
    // scroller together), so no scrollLeft term is needed.
    function box(el){var r=el.getBoundingClientRect();
      return {left:r.left-kb.left,right:r.right-kb.left,y:r.top-kb.top+r.height/2};}
    var cards=cols.map(function(col){return [].slice.call(col.querySelectorAll('.km'));});
    var made=0;
    for(var ci=1;ci<cards.length;ci++){
      for(var i=0;i<cards[ci].length;i++){
        var child=box(cards[ci][i]);
        [cards[ci-1][i*2],cards[ci-1][i*2+1]].forEach(function(p){
          if(!p)return;
          var pc=box(p);
          var x1=pc.right,y1=pc.y,x2=child.left,y2=child.y,mx=Math.round((x1+x2)/2);
          var d='M'+x1+' '+y1+' H'+mx+' V'+y2+' H'+x2;   // right angles only
          var path=document.createElementNS('http://www.w3.org/2000/svg','path');
          path.setAttribute('d',d);path.setAttribute('class','bz-link');path.setAttribute('fill','none');
          // Highlight only the segment LEAVING a watched team's game (its path
          // forward) — never the opponent's feed into that next game.
          if(p.classList.contains('has-watched'))path.setAttribute('data-watched','1');
          svg.appendChild(path);made++;
        });
      }
    }
    tree.setAttribute('data-links',made);
  }
  var rzTimer;
  function scheduleDraw(){clearTimeout(rzTimer);rzTimer=setTimeout(drawBracket,60);}
  // Box heights depend on how many candidate flags wrap, which depends on the
  // emoji metrics — and those can land AFTER our first measure (font/emoji paint),
  // leaving stale positions (overlaps). Re-lay out once fonts are ready and again
  // whenever any box actually changes size. Layout only moves boxes (never resizes
  // them), so observing size changes can't loop.
  function wireBracketObserver(){
    var tree=document.querySelector('.kbracket');
    if(!tree)return;
    if(document.fonts&&document.fonts.ready)document.fonts.ready.then(scheduleDraw);
    if(typeof ResizeObserver==='undefined')return;
    var ro=new ResizeObserver(scheduleDraw);
    tree.querySelectorAll('.km,.champion-plinth').forEach(function(el){ro.observe(el);});
  }


  // Entrance motion: progressive enhancement only. Content is visible by default
  // (CSS). We opt the page into a CSS-only fade-up — which always ENDS visible —
  // unless the user prefers reduced motion, in which case we leave it untouched.
  function wireReveal(){
    var mq=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)');
    if(mq&&mq.matches)return; // honor reduced motion: no entrance animation at all
    document.documentElement.classList.add('reveal-ready');
  }

  // Live scores: overlay ESPN's public feed onto in-progress matches. The static
  // site only knows FINAL scores (openfootball posts at full time), so a match
  // that is live right now renders as "Kicks off …" until then. This fills in the
  // live score + minute and a LIVE pulse, polling every 30s while anything is in
  // play. Pure progressive enhancement: if /api/live is unreachable (e.g. local
  // preview) it silently no-ops and the static site stands on its own.
  function liveCanon(s){
    // NFKD splits accents off (ü -> u+◌̈); the final [^a-z0-9] strip then drops the
    // combining marks and punctuation, so "Türkiye"->turkiye, "Curaçao"->curacao.
    s=(s||'').normalize('NFKD').toLowerCase().replace(/&/g,'and').replace(/[^a-z0-9]/g,'');
    var A={bosniaandherzegovina:'bosnia',bosniaherzegovina:'bosnia',czechrepublic:'czech',
      czechia:'czech',drcongo:'congodr',congodr:'congodr',turkey:'turkey',turkiye:'turkey',
      usa:'usa',unitedstates:'usa'};
    return A[s]||s;
  }
  function livePair(a,b){var x=liveCanon(a),y=liveCanon(b);return x<y?x+'~'+y:y+'~'+x;}
  function wireLive(){
    var nodes=document.querySelectorAll('[data-live]');
    if(!nodes.length)return;
    var idx={};
    nodes.forEach(function(el){
      var names=[];
      el.querySelectorAll('[data-team]').forEach(function(t){
        var n=t.getAttribute('data-team');if(n)names.push(n);});
      if(names.length<2)return;
      var k=livePair(names[0],names[1]);
      (idx[k]=idx[k]||[]).push(el);
    });
    if(!Object.keys(idx).length)return;
    function paint(el,m){
      if(el.classList.contains('is-done'))return;        // official FT already shown
      if(m.s1==null||m.s2==null)return;
      var teams=el.querySelectorAll('[data-team]');
      var firstIsHome=liveCanon(teams[0].getAttribute('data-team'))===liveCanon(m.t1);
      var g1=firstIsHome?m.s1:m.s2, g2=firstIsHome?m.s2:m.s1;
      var mid=el.querySelector('[data-live-mid]');
      if(mid){
        mid.innerHTML='<b class="sg'+(g1>g2?' win':'')+'">'+g1+'</b>'+
          '<span class="sdash">–</span><b class="sg'+(g2>g1?' win':'')+'">'+g2+'</b>';
        mid.classList.add('live-mid');
      }
      var inplay=m.state==='in';
      el.classList.toggle('is-live',inplay);
      el.classList.toggle('is-livedone',m.state==='post');
      var tag=el.querySelector('[data-live-tag]');
      if(tag){
        tag.hidden=false;
        tag.className=tag.className.replace(/\b(up|done|live)\b/g,'').replace(/\s+/g,' ').trim();
        if(inplay){tag.textContent=m.clock||'LIVE';tag.className+=' live';}
        else{tag.textContent='FT';tag.className+=' done';}
      }
    }
    var timer=null;
    function schedule(any){clearTimeout(timer);
      if(any&&document.visibilityState!=='hidden')timer=setTimeout(poll,30000);}
    function poll(){
      fetch('/api/live',{headers:{accept:'application/json'}})
       .then(function(r){return r.ok?r.json():null;})
       .then(function(d){
         if(!d||!d.ok||!d.matches){schedule(false);return;}
         var any=false;
         d.matches.forEach(function(m){
           if(m.state==='pre')return;
           var list=idx[livePair(m.t1,m.t2)];if(!list)return;
           if(m.state==='in')any=true;
           list.forEach(function(el){paint(el,m);});
         });
         schedule(any);
       }).catch(function(){schedule(false);});
    }
    document.addEventListener('visibilitychange',function(){
      if(document.visibilityState==='visible')poll();});
    window.__wcPollLive=poll;                              // diagnostic / test seam
    poll();
  }

  function wireBracketScroll(){
    var wrap=document.querySelector('[data-bracket] .bracket-wrap');
    if(!wrap)return;
    wrap.addEventListener('scroll',updateEdges,{passive:true});
  }
  // On a phone the columns scroll-snap one at a time; open on the CURRENT round
  // (left-aligned), or the far-right column right-aligned. Once only — don't yank
  // the user back on later redraws.
  function landOnActiveColumn(){
    if(window.innerWidth>=720)return;
    var wrap=document.querySelector('[data-bracket] .bracket-wrap');
    var tree=wrap&&wrap.querySelector('.kbracket');
    if(!wrap||!tree)return;
    var cols=tree.querySelectorAll('.kr-col');
    var on=document.querySelector('.brn-item.on');
    var idx=Math.min(on?parseInt(on.getAttribute('data-rd'),10)||0:0, cols.length-1);
    var col=cols[idx]; if(!col)return;
    var target=(idx===cols.length-1)
      ? col.offsetLeft+col.offsetWidth-wrap.clientWidth     // last: right-aligned
      : col.offsetLeft-14;                                  // else: left-aligned
    wrap.scrollLeft=Math.max(0,target);
    updateEdges();
  }

  document.addEventListener('DOMContentLoaded',function(){
    wireTZ();apply();wireReveal();wireLive();wireBracketScroll();wireBracketObserver();drawBracket();
    landOnActiveColumn();
  });
  window.addEventListener('load',drawBracket);
  window.addEventListener('resize',scheduleDraw);
})();
"""

STYLE = r"""
/* ===================================================================
   "BROADCAST INK"  —  World Cup 2026 tracker visual system
   Newsprint paper ground, near-black ink, ONE electric vermilion that
   means live / advancing / primary only. Heavy neo-grotesque display +
   tracked monospace labels. Hard edges, hairline rules, a baseline grid.
   =================================================================== */
:root{
  /* palette ---------------------------------------------------------- */
  --paper:#F4F2EC;        /* newsprint ground */
  --paper2:#ECEAE1;       /* recessed panel */
  --paper3:#E3E0D5;       /* deepest tint */
  --ink:#13110D;          /* near-black ink */
  --ink2:#3A372F;         /* secondary ink */
  --muted-c:#6A6458;      /* meta / muted */
  --line:rgba(19,17,13,.16);      /* hairline rule */
  --line2:rgba(19,17,13,.30);     /* heavier rule */
  --hair:rgba(19,17,13,.09);
  --bg-rule:rgba(19,17,13,.055);  /* faint background ruling — subtler than hairlines */
  --zebra:rgba(19,17,13,.04);     /* alternating standings row tint */
  --text:var(--ink);--text-dim:var(--ink2);--muted:var(--muted-c);
  --vermilion:#FF3B14;    /* THE single accent literal (one source) */
  --accent:var(--vermilion);      /* global signal token (overridden per-team on tcard/team-hero only) */
  --accent2:var(--vermilion);
  --sig:var(--vermilion);         /* watched / live signal — never overridden */
  --ring:var(--vermilion);        /* focus accent */
  --on-accent:#FFF4F0;            /* text on a vermilion block */
  /* semantic outcome (kept as ink tints + the one accent; never teal) */
  --c-in:var(--ink);              /* qualify = solid ink fill */
  --c-bub:#B8B2A2;                /* bubble = warm grey */
  --c-out:#D8D4C7;                /* out = pale grey */
  --c-gone:var(--muted-c);
  /* type — neo-grotesque display + tracked mono labels */
  --sans:"Helvetica Neue",Helvetica,"Inter",Arial,system-ui,-apple-system,sans-serif;
  --mono:ui-monospace,"SF Mono",Menlo,Consolas,"Roboto Mono",monospace;
  /* fluid display scale (tight, confident) */
  --t-hero:clamp(3rem,1.2rem + 9.2vw,8.4rem);
  --t-3xl:clamp(2.3rem,1.3rem + 4.6vw,4.4rem);
  --t-2xl:clamp(1.7rem,1.2rem + 2.5vw,2.9rem);
  --t-xl:clamp(1.35rem,1.1rem + 1.2vw,1.85rem);
  --t-lg:clamp(1.1rem,1rem + .5vw,1.3rem);
  --t-md:1rem;--t-sm:.84rem;--t-xs:.72rem;--t-2xs:.64rem;
  /* spacing — 8px rhythm */
  --s1:4px;--s2:8px;--s3:12px;--s4:16px;--s5:24px;--s6:32px;--s7:48px;--s8:72px;
  --maxw:1200px;
  --r:3px;--r-sm:2px;--r-lg:4px;   /* hard edges */
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--paper);color:var(--ink);overflow-x:hidden;-webkit-font-smoothing:antialiased;
  font:16px/1.5 var(--sans);
  /* baseline-grid newsprint motif: a faint horizontal ruling, no aurora/pitch */
  background-image:repeating-linear-gradient(180deg,transparent 0,transparent 31px,var(--bg-rule) 31px,var(--bg-rule) 32px);
  background-attachment:fixed}
a{color:inherit;text-decoration:none}
img{max-width:100%}
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);clip-path:inset(50%);white-space:nowrap;border:0;max-width:1px}
h1,h2,h3,h4{line-height:1.02;margin:0 0 .4em;letter-spacing:-.03em;font-weight:800;text-transform:uppercase}
h1{font-size:var(--t-3xl)}h2{font-size:var(--t-2xl)}h3{font-size:var(--t-lg)}h4{font-size:var(--t-md)}
.muted{color:var(--muted);font-size:.86em}
b,strong{font-weight:800}
main{max-width:var(--maxw);margin:0 auto;padding:var(--s5) clamp(14px,4vw,28px) var(--s8);position:relative;z-index:1}

/* mono label primitive (overline) ----------------------------------- */
.eyebrow,.hs-k,.hp-k,.foot-k,.hn-k,.yt-k,.odds-h,.race-h,.kr-head,.gb-tag,.th-eyebrow,.dist-advh,
.pz-grp,.pz-tag,.live-tag,.km-no,.road-rd,.road-vs,.road-track,.badge,.th-badge,.dir-head .muted,
.group-head .muted,.standings th,.km-m,.bcode,.cp-lbl{
  font-family:var(--mono);font-weight:700;text-transform:uppercase;letter-spacing:.12em}

/* skip link + focus ------------------------------------------------- */
.skip-link{position:fixed;left:var(--s3);top:-60px;z-index:100;background:var(--ink);
  color:var(--paper);border:2px solid var(--vermilion);border-radius:var(--r);padding:10px 16px;
  font-family:var(--mono);font-weight:700;text-transform:uppercase;letter-spacing:.1em;transition:top .18s}
.skip-link:focus{top:var(--s3);outline:none}
:focus-visible{outline:none}
a:focus-visible,button:focus-visible,input:focus-visible,[tabindex]:focus-visible{
  outline:3px solid var(--vermilion);outline-offset:2px;border-radius:var(--r-sm)}
.wl-ic:focus-visible{outline:3px solid var(--vermilion);outline-offset:3px;border-radius:var(--r-sm)}

/* sections + reveal ------------------------------------------------- */
section{margin:var(--s8) 0}
section:first-of-type{margin-top:var(--s4)}
/* Entrance: transform/opacity only (no reflow -> CLS ~0). Always ends visible.
   The .reveal-ready hook is added by JS only when motion is allowed. */
[data-reveal]{opacity:1}
.reveal-ready [data-reveal]{animation:fadeUp .55s both cubic-bezier(.2,.7,.2,1)}
.reveal-ready [data-reveal]:nth-of-type(2){animation-delay:.05s}
.reveal-ready [data-reveal]:nth-of-type(3){animation-delay:.1s}
.reveal-ready [data-reveal]:nth-of-type(4){animation-delay:.15s}
@keyframes fadeUp{from{opacity:0;transform:translate3d(0,18px,0)}to{opacity:1;transform:none}}
.sec-head{display:flex;align-items:flex-end;gap:var(--s3);flex-wrap:wrap;margin-bottom:var(--s5);
  padding-bottom:10px;border-bottom:2px solid var(--ink)}
.sec-head h2{margin:0;position:relative;padding-left:20px;line-height:.95}
.sec-head h2::before{content:"";position:absolute;left:0;top:.08em;bottom:.08em;width:9px;background:var(--vermilion)}
.sec-head .muted{font-family:var(--mono);font-size:var(--t-xs);text-transform:uppercase;letter-spacing:.1em;margin-left:auto;text-align:right}

/* header ------------------------------------------------------------ */
.site-head{position:sticky;top:0;z-index:30;display:flex;align-items:stretch;
  justify-content:space-between;background:var(--paper);border-bottom:2px solid var(--ink)}
.brand{flex-shrink:0;min-width:0;display:flex}
.brand a{display:inline-flex;align-items:center;gap:11px;padding:12px clamp(14px,3vw,26px);
  border-right:2px solid var(--ink)}
.wm-mark{display:inline-flex;line-height:0}
.wm-text{display:flex;flex-direction:column;line-height:1;font-family:var(--mono);font-weight:800}
.wm-l1{font-size:.78rem;letter-spacing:.18em;color:var(--ink)}
.wm-l2{font-size:.78rem;letter-spacing:.18em;color:var(--muted)}
.wm-yr{color:var(--vermilion)}
.site-nav{display:flex}
.site-nav a{display:inline-flex;align-items:center;padding:0 clamp(12px,2.2vw,22px);
  font-family:var(--mono);font-weight:700;text-transform:uppercase;letter-spacing:.1em;font-size:.78rem;
  color:var(--muted);border-left:1px solid var(--line);transition:color .12s,background .12s}
.site-nav a:hover{color:var(--ink);background:var(--paper2)}
.site-nav a.on{color:var(--paper);background:var(--ink)}
.site-nav a.on:hover{background:var(--ink)}

/* Live Wire signal (now-divider dot, bracket edge, footer dot) ------ */
.wire{position:relative}
.wire-pulse{display:inline-block;width:8px;height:8px;border-radius:50%;
  background:var(--vermilion);box-shadow:0 0 0 0 rgba(255,59,20,.6);animation:wirePulse 2s ease-out infinite}
@keyframes wirePulse{0%{box-shadow:0 0 0 0 rgba(255,59,20,.55)}70%{box-shadow:0 0 0 9px rgba(255,59,20,0)}100%{box-shadow:0 0 0 0 rgba(255,59,20,0)}}

/* ============ HERO (type-led, no pills / eyebrow / subtitle) ======= */
.hero{position:relative;margin-top:0;padding:0 0 var(--s6);border-bottom:3px solid var(--ink)}
.hero-strip{display:flex;flex-wrap:wrap;border-bottom:2px solid var(--ink);margin-bottom:clamp(18px,3vw,38px)}
.hs-cell{display:flex;flex-direction:column;gap:3px;padding:12px 18px 14px;border-right:1px solid var(--line);min-width:0}
.hs-cell:first-child{padding-left:0}
.hs-k{font-family:var(--mono);font-size:.62rem;letter-spacing:.18em;color:var(--muted)}
.hs-v{font-family:var(--mono);font-weight:800;font-size:.96rem;letter-spacing:.02em;color:var(--ink);
  text-transform:uppercase;font-variant-numeric:tabular-nums}
.hs-of{color:var(--muted);font-weight:700}
.hs-host{margin-left:auto;border-right:0;text-align:right;align-items:flex-end}
.hero-title{font-size:var(--t-hero);line-height:.86;letter-spacing:-.045em;margin:0;color:var(--ink);
  font-weight:800;text-transform:uppercase}
.ht-big{display:inline-block}
/* "LIVE" is a broadcast lower-third: a solid vermilion block wiping in behind
   paper-knockout text. transform/opacity only (no layout shift). */
.ht-live{position:relative;display:inline-block;color:var(--on-accent);padding:0 .12em;margin-left:.04em}
.ht-live::before{content:"";position:absolute;left:0;right:0;top:.02em;bottom:.04em;background:var(--vermilion);
  z-index:-1;transform:scaleX(1);transform-origin:left}
.reveal-ready .ht-live::before{animation:liveWipe .7s .25s backwards cubic-bezier(.2,.7,.2,1)}
@keyframes liveWipe{from{transform:scaleX(0)}to{transform:scaleX(1)}}
.hero-foot{display:flex;gap:clamp(20px,4vw,56px);align-items:flex-end;flex-wrap:wrap;margin-top:clamp(22px,4vw,44px)}
.hero-prog{flex:1;min-width:280px}
.hp-head{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px}
.hp-k{font-size:.66rem;letter-spacing:.18em;color:var(--muted)}
.hp-pct{font-family:var(--mono);font-weight:800;font-size:1.7rem;color:var(--ink);font-variant-numeric:tabular-nums}
.hp-of{font-size:.55em;color:var(--muted);margin-left:1px}
.hp-scale{display:flex;justify-content:space-between;margin-top:7px;font-family:var(--mono);
  font-size:.6rem;letter-spacing:.06em;color:var(--muted);text-transform:uppercase}
.hero-next{flex:0 0 auto;border-left:2px solid var(--ink);padding-left:clamp(16px,3vw,28px);max-width:46%}
.hn-k{display:block;font-size:.62rem;letter-spacing:.18em;color:var(--muted);margin-bottom:6px}
.hn-v{font-family:var(--mono);font-weight:800;font-size:clamp(.95rem,1.6vw,1.25rem);color:var(--ink);line-height:1.15}

/* ============ TALLY DEVICE (signature, recurs as a system) ========= */
/* A segmented horizontal meter with a hard qualification-threshold tick. */
.tally{position:relative;display:block;height:var(--tally-h,30px);background:var(--paper3);
  border:2px solid var(--ink);overflow:hidden}
.tally .tally-fill{position:absolute;left:0;top:0;bottom:0;background:var(--vermilion);
  transition:width .55s cubic-bezier(.3,.8,.3,1)}
.tally .tally-tick{position:absolute;top:-3px;bottom:-3px;width:3px;background:var(--ink);
  transform:translateX(-50%);z-index:3;box-shadow:0 0 0 2px var(--paper)}
.tally .tally-tick::after{content:"";position:absolute;left:50%;top:-6px;width:8px;height:8px;
  background:var(--ink);transform:translateX(-50%) rotate(45deg)}
.hero-tally{--tally-h:34px}
.mini-tally{--tally-h:14px;border-width:1.5px;min-width:54px}
.mini-tally .tally-tick{box-shadow:0 0 0 1.5px var(--paper)}
.mini-tally .tally-tick::after{display:none}
/* segmented variant (the in/bubble/out distribution bar) */
.dist-bar.tally{display:flex;border:2px solid var(--ink);background:var(--paper3)}
.dist-bar.tally .tally-tick::after{top:-7px}

/* ============ PULSE BAND (matchday ribbon) ======================== */
.pulse-section{margin-top:var(--s7)}
.pulse-head h2{margin:0}
.pulse-band{display:flex;flex-wrap:nowrap;gap:0;overflow-x:auto;padding:0;border:2px solid var(--ink);
  scroll-snap-type:x proximity;-webkit-overflow-scrolling:touch;background:var(--paper)}
.pz{flex:0 0 232px;scroll-snap-align:start;background:var(--paper);border-right:1px solid var(--line);
  padding:13px 15px;transition:background .14s}
.pz:hover{background:var(--paper2)}
.pz.is-upcoming{background:var(--paper2)}
.pz.has-watched{background:var(--paper);box-shadow:inset 5px 0 0 var(--sig)}
.pz-head{display:flex;align-items:center;gap:7px;font-size:.6rem;margin-bottom:11px}
.pz-grp{font-size:.6rem;letter-spacing:.12em;color:var(--ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:96px}
.pz-tag{margin-left:auto;font-size:.58rem;padding:2px 7px;border:1px solid var(--ink);letter-spacing:.1em}
.pz-tag.done{background:var(--ink);color:var(--paper)}
.pz-tag.up{background:transparent;color:var(--muted);border-color:var(--line2)}
.pz-date{font-family:var(--mono);font-weight:600;color:var(--muted);font-size:.62rem}
.pz-row{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:8px}
.pz-team{display:flex;align-items:center;gap:6px;min-width:0;font-weight:700;font-size:.86rem}
.pz-team:last-child{justify-content:flex-end;text-align:right}
.pz-team .fl{font-size:1.1em}
.pz-team .nm{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pz-team.watched .nm{color:var(--sig)}
.pz-score{display:flex;align-items:center;gap:2px;font-family:var(--mono);font-weight:800;font-size:1.15rem;font-variant-numeric:tabular-nums}
.pz-score .sg{color:var(--muted)}.pz-score .sg.win{color:var(--ink)}
.pz-score .sdash{color:var(--muted);margin:0 1px}
.pz-ko{font-family:var(--mono);font-weight:800;font-size:.98rem;color:var(--ink);font-variant-numeric:tabular-nums;white-space:nowrap}
.pz-foot,.m-scorers{margin-top:10px;font-family:var(--mono);font-size:.62rem;line-height:1.5;display:flex;flex-wrap:wrap;gap:3px 9px;color:var(--muted)}
.m-scorers .scorer,.pz .scorer{color:var(--ink2);white-space:nowrap}
.m-scorers .scorer::before,.pz .scorer::before{content:"›";margin-right:4px;color:var(--vermilion);font-weight:800}
.now-divider{flex:0 0 auto;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:9px;
  align-self:stretch;padding:0 10px;position:relative;background:var(--ink)}
.now-divider .wire-pulse{width:11px;height:11px;z-index:1}
.now-lbl{font-family:var(--mono);font-size:.6rem;font-weight:800;letter-spacing:.2em;color:var(--paper);
  writing-mode:vertical-rl;transform:rotate(180deg);z-index:1}

/* ============ LIVE STATE (broadcast scorebug) ===================== */
/* A resting/upcoming match is quiet ink-on-paper; .is-live lights the whole
   lockup with the single accent; .is-livedone reverts to a finished read.
   All color references resolve from --accent/--sig (no hardcoded reds). */
.live-tag{display:none;font-family:var(--mono);font-weight:800;letter-spacing:.12em;padding:2px 8px;
  font-size:.6rem;font-variant-numeric:tabular-nums;border:1px solid var(--ink);color:var(--ink)}
.live-tag.live,.pz-tag.live{display:inline-flex;align-items:center;gap:6px;
  background:var(--accent);color:var(--on-accent);border-color:var(--accent)}
.live-tag.done,.pz-tag.done{display:inline-flex}
.pz-tag.live::before,.live-tag.live::before{content:"";width:6px;height:6px;border-radius:50%;
  background:var(--on-accent);box-shadow:0 0 0 0 rgba(255,255,255,.7);animation:livedot 1.4s ease-out infinite}
@keyframes livedot{70%{box-shadow:0 0 0 6px rgba(255,255,255,0)}100%{box-shadow:0 0 0 0 rgba(255,255,255,0)}}
.pz.is-live{box-shadow:inset 0 0 0 3px var(--accent);background:var(--paper)}
.pz.is-live .pz-ko,.pz.is-live .pz-score{color:var(--accent)}
.pz.is-livedone{box-shadow:inset 5px 0 0 var(--ink)}
.match.is-live{outline:3px solid var(--accent);outline-offset:-3px;background:var(--paper)}
.match.is-live .score{color:var(--accent)}
.match.is-livedone{outline:1px solid var(--line2);outline-offset:-1px}
.pz-ko.live-mid,.vs.live-mid{display:inline-flex;align-items:center;gap:2px;color:var(--accent);font-family:var(--mono);font-variant-numeric:tabular-nums}
@media(prefers-reduced-motion:reduce){.pz-tag.live::before,.live-tag.live::before{animation:none}}

/* ============ MATCH LINE ========================================== */
.match-list{display:flex;flex-direction:column;gap:-1px}
.match-list>.match{margin-top:-1px}
.match{position:relative;background:var(--paper);border:1px solid var(--line2);padding:11px 15px;transition:background .14s}
.match:hover{background:var(--paper2)}
.match.has-watched{box-shadow:inset 5px 0 0 var(--sig)}
.m-meta{display:flex;gap:9px;align-items:center;font-family:var(--mono);font-size:.62rem;color:var(--muted);
  margin-bottom:7px;flex-wrap:wrap;text-transform:uppercase;letter-spacing:.08em}
.m-grp{font-weight:800;color:var(--ink)}
.m-row{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:16px}
.m-side{display:flex;align-items:center;min-width:0}
.m-side.a{justify-content:flex-end;text-align:right}
.m-side.b{justify-content:flex-start}
.m-side .nm{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.score{display:inline-flex;align-items:center;gap:3px;font-family:var(--mono);font-weight:800;font-size:1.2rem;white-space:nowrap;font-variant-numeric:tabular-nums}
.score .sg{color:var(--muted)}.score .sg.win{color:var(--ink)}.score .sdash{color:var(--muted);margin:0 2px}
.pens{font-family:var(--mono);font-size:.66rem;color:var(--muted);margin-left:4px}
.vs{font-family:var(--mono);color:var(--muted);font-weight:700;font-size:.84rem;white-space:nowrap;font-variant-numeric:tabular-nums}
.rd{font-family:var(--mono);background:var(--ink);color:var(--paper);padding:1px 7px;font-size:.6rem;font-weight:700;letter-spacing:.08em}
/* Kickoff stamp — the day reads muted, the time in ink, the zone in the one
   accent: variance by colour, not by jarring size jumps. Em-relative everywhere. */
.ko{display:inline-flex;align-items:baseline;gap:.6ch;white-space:nowrap}
.ko-day{font-weight:600;color:var(--muted);letter-spacing:.02em}
.ko-time{font-weight:800;color:var(--ink);font-variant-numeric:tabular-nums}
.ko-tz{font-weight:700;color:var(--vermilion);margin-left:.4ch;font-size:.9em;letter-spacing:.03em}
.m-meta .ko-day,.m-meta .ko-time{text-transform:none}
.pz-tz{font-weight:700;color:var(--vermilion);margin-left:.3ch;font-size:.62em;letter-spacing:.03em}
/* "Knocked out" marker in standings (compact tables) */
.ko-out{display:inline-block;margin-left:7px;font-family:var(--mono);font-size:.5rem;font-weight:800;
  letter-spacing:.1em;color:var(--muted);border:1px solid var(--line2);padding:0 4px;vertical-align:middle}
.standings tr.gone .ko-out{border-color:var(--c-out)}
/* Next-knockout callout on a team page */
.next-ko{border:2px solid var(--ink);background:var(--paper2);margin-bottom:18px}
.nk-head{display:flex;align-items:center;justify-content:space-between;gap:10px;background:var(--ink);color:var(--paper);padding:7px 13px}
.nk-k{font-family:var(--mono);font-size:.62rem;font-weight:800;letter-spacing:.12em;text-transform:uppercase}
.nk-rd{font-family:var(--mono);font-size:.6rem;font-weight:800;letter-spacing:.08em;color:var(--vermilion)}
.next-ko .match{padding:13px 15px}
.next-ko .match.is-upcoming{border-left:0}

/* ============ TEAM LINKS / CHIPS ================================== */
.team,.cand,.bteam{display:inline-flex;align-items:center;gap:6px;font-weight:700;padding:1px 4px;transition:background .12s,color .12s}
.team .fl,.cand .fl,.bteam .fl{font-size:1.08em;line-height:1}
.team:hover,.cand:hover,.bteam:hover{color:var(--ink);background:var(--paper3)}
.team.watched,.cand.watched,.bteam.watched,.cal-tm.watched{box-shadow:inset 0 -2px 0 var(--sig);color:var(--ink);font-weight:800}
.cand{font-family:var(--mono);font-size:.72rem;background:var(--paper2);border:1px solid var(--line);padding:2px 7px}
.cand.watched{background:var(--paper);box-shadow:inset 0 0 0 1.5px var(--sig)}
.slot{display:inline-flex;flex-direction:column;gap:3px}
.slot-label{font-family:var(--mono);color:var(--muted);font-weight:700;font-size:.78em;text-transform:uppercase;letter-spacing:.06em}
.slot-cands{display:flex;flex-wrap:wrap;gap:4px}

/* ============ TABLES / STANDINGS ================================== */
.card{background:var(--paper);border:2px solid var(--ink)}
.group-card{overflow:hidden}
.group-card.solo{overflow-x:auto;width:100%;max-width:820px;margin:0 auto}
.group-card.solo .standings{width:100%}
.group-head{display:flex;justify-content:space-between;align-items:center;padding:12px 16px;border-bottom:2px solid var(--ink);background:var(--paper)}
.group-head h3{margin:0;font-size:1rem;letter-spacing:-.01em}
.group-link{display:inline-flex;align-items:baseline;gap:4px}
.group-link .arrow{color:var(--vermilion);transition:transform .15s;display:inline-block;font-weight:800}
.group-link:hover .arrow{transform:translateX(4px)}
.group-head .muted{font-size:.62rem;color:var(--muted);letter-spacing:.1em}
table.standings{width:100%;border-collapse:collapse;font-size:.85rem}
.standings th,.standings td{padding:9px 8px;text-align:center}
.standings thead tr{border-bottom:2px solid var(--ink)}
.standings th{color:var(--muted);font-size:.56rem;letter-spacing:.08em}
.standings .tm{text-align:left;width:100%}
.group-card.solo .standings .tm{width:auto;padding-right:20px}
.standings td.pos{color:var(--ink);width:24px;font-family:var(--mono);font-weight:800;font-variant-numeric:tabular-nums}
.standings td.star{width:24px;padding:0}
.standings td.pts{font-family:var(--mono);font-weight:800;font-variant-numeric:tabular-nums}
.standings td:not(.tm):not(.st):not(.odds):not(.race){font-family:var(--mono);font-variant-numeric:tabular-nums}
.standings .gd{color:var(--muted)}
.group-card:not(.solo) .standings .hide-s{display:none}  /* GF/GA only on the detail page; compact home boxes show P W D L GD Pts */
.standings tbody tr{transition:background .12s}
.standings tbody tr:nth-child(even){background:var(--zebra)}
.standings tbody tr:hover{background:var(--paper2)}
.standings tr.qual td.pos{box-shadow:inset 4px 0 0 var(--vermilion)}
.standings tr.third td.pos{box-shadow:inset 4px 0 0 var(--ink)}
.standings tr.gone td.pos{box-shadow:inset 4px 0 0 var(--c-out)}
.standings tr.gone{opacity:.55}
.standings tbody tr.watched{background:var(--paper2)}
.standings tr.watched td.tm{box-shadow:inset 0 -2px 0 var(--sig)}
.standings .st{white-space:nowrap}
.standings td.odds,.standings td.race{min-width:92px;white-space:nowrap;padding-right:10px}
.standings td.odds .mini-tally,.standings td.race .mini-tally{display:inline-block;width:58px;vertical-align:middle}
.odds-n{font-family:var(--mono);font-weight:800;font-size:.74rem;margin-left:6px;font-variant-numeric:tabular-nums}
.r32{font-family:var(--mono);font-weight:800;font-size:.72rem}
.badge,.th-badge{display:inline-flex;align-items:center;gap:5px;font-size:.58rem;border:1.5px solid var(--ink);padding:3px 8px;white-space:nowrap}
.badge .bdot{width:6px;height:6px;border-radius:50%;background:currentColor}
.badge.win,.th-badge.win{background:var(--vermilion);color:var(--on-accent);border-color:var(--vermilion)}
.badge.q,.th-badge.q{background:var(--ink);color:var(--paper);border-color:var(--ink)}
.badge.bub,.th-badge.bub{background:transparent;color:var(--ink);border-color:var(--ink)}
.badge.gone,.th-badge.gone{background:transparent;color:var(--muted);border-color:var(--line2)}
.th-badge.work{background:transparent;color:var(--ink2);border-color:var(--line2)}
.group-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(430px,1fr));gap:var(--s4)}
.thirds-card{overflow-x:auto}
.thirds td{padding:9px 6px}

/* star buttons ------------------------------------------------------ */
.wl-ic{width:30px;height:30px;border:0;background:none;cursor:pointer;color:var(--muted);
  font-size:1.15rem;line-height:1;padding:0;transition:color .12s,transform .12s}
.wl-ic::before{content:"\2606"}
.wl-ic:hover{color:var(--vermilion);transform:scale(1.16)}
.wl-ic.on{color:var(--vermilion)}.wl-ic.on::before{content:"\2605"}
.wl{display:inline-flex;align-items:center;gap:8px;cursor:pointer;border:2px solid var(--ink);
  background:var(--paper);color:var(--ink);font-family:var(--mono);font-weight:700;font-size:.74rem;
  text-transform:uppercase;letter-spacing:.08em;padding:10px 18px;min-height:44px;transition:background .14s,color .14s}
.wl:hover{background:var(--paper2)}
.wl.on{background:var(--vermilion);border-color:var(--vermilion);color:var(--on-accent)}
.wl .wl-star{color:inherit}

/* your teams + directory -------------------------------------------- */
.your-teams-sec{position:relative}
.tcard-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(238px,1fr));gap:12px}
.yt-grid{grid-template-columns:repeat(auto-fill,minmax(268px,1fr));gap:14px}
.tcard{position:relative;display:flex;flex-direction:column;background:var(--paper);border:2px solid var(--ink);
  overflow:hidden;transition:transform .14s}
.tcard::before{content:"";position:absolute;left:0;top:0;bottom:0;width:6px;background:var(--accent);z-index:1}
.tcard:hover{transform:translateY(-2px)}
.tcard.watched{box-shadow:4px 4px 0 var(--sig)}
.tcard.watched::before{width:6px;background:var(--sig)}
.tcard-top{display:flex;align-items:center;gap:11px;padding:13px 15px}
.tcard-main{display:flex;align-items:center;gap:12px;flex:1;min-width:0}
.tcard-flag{font-size:1.7rem;line-height:1}
.tcard-body{display:flex;flex-direction:column;min-width:0;gap:2px}
.tcard-name{font-weight:800;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-transform:uppercase;letter-spacing:-.01em}
.tcard-meta{font-family:var(--mono);font-size:.66rem;text-transform:uppercase;letter-spacing:.05em}
/* watchlist card: next match (primary) + most recent result (secondary) */
.tcard-fix{display:flex;flex-direction:column;gap:7px;padding:0 15px 13px;border-top:1px solid var(--line);margin-top:-2px;padding-top:11px}
.tc-fix{display:flex;align-items:baseline;gap:9px;min-width:0;font-size:.74rem}
.tc-k{flex:0 0 30px;font-family:var(--mono);font-size:.54rem;font-weight:800;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
.tc-k.out{color:var(--vermilion)}
.tc-line{display:flex;align-items:baseline;gap:7px;flex-wrap:wrap;min-width:0}
.tc-vs{color:var(--ink2)}
.tc-vs .tc-opp,.tc-vs .cand{font-weight:700;color:var(--ink)}
.tc-rd{font-family:var(--mono);font-size:.52rem;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:var(--paper);background:var(--ink2);padding:1px 5px}
.tc-res{font-family:var(--mono);font-weight:800;font-variant-numeric:tabular-nums}
.tc-res.w{color:var(--ink)}.tc-res.l{color:var(--muted)}.tc-res.d{color:var(--ink2)}
.tc-cands{color:var(--muted);font-style:italic}
.tc-next .tc-k{color:var(--vermilion)}
.yt-empty{display:flex;align-items:center;gap:22px;padding:30px 30px;border:2px dashed var(--line2);background:var(--paper2)}
.yt-star{font-size:3rem;color:var(--vermilion);line-height:1;flex:0 0 auto}
.yt-empty-body{display:flex;flex-direction:column;gap:8px;max-width:560px}
.yt-k{font-family:var(--mono);font-size:.62rem;letter-spacing:.18em;color:var(--muted)}
.yt-h{font-size:1.6rem;text-transform:uppercase;letter-spacing:-.02em;line-height:1}
.yt-p{color:var(--ink2);font-size:.92rem;line-height:1.5}
.yt-inline{color:var(--vermilion);font-weight:800}
.yt-cta a{font-family:var(--mono);font-weight:800;text-transform:uppercase;letter-spacing:.08em;font-size:.74rem;
  color:var(--ink);box-shadow:inset 0 -2px 0 var(--vermilion)}
.yt-cta a:hover{background:var(--vermilion);color:var(--on-accent);box-shadow:none}
.directory{display:flex;flex-direction:column;gap:var(--s6)}
.dir-group .dir-head{margin-bottom:12px;display:flex;align-items:baseline;gap:10px;font-size:1.1rem;
  font-weight:800;text-transform:uppercase;letter-spacing:-.01em;padding-bottom:7px;border-bottom:2px solid var(--ink)}
.dir-group .dir-head a:hover{color:var(--vermilion)}
.dir-group .dir-head .muted{font-size:.62rem;letter-spacing:.1em;margin-left:auto}
.search-wrap{position:relative;max-width:440px;margin-bottom:var(--s5)}
.search-ic{position:absolute;left:14px;top:50%;transform:translateY(-50%);color:var(--muted);font-size:1.1rem;pointer-events:none}
.team-search{width:100%;padding:13px 16px 13px 40px;border:2px solid var(--ink);background:var(--paper);color:var(--ink);
  font-family:var(--mono);font-size:.92rem}
.team-search::placeholder{color:var(--muted)}
.team-search:focus-visible{outline:3px solid var(--vermilion);outline-offset:0}
.search-empty{font-family:var(--mono);text-transform:uppercase;letter-spacing:.08em;font-size:.78rem}
.empty{padding:18px;border:2px dashed var(--line2);background:var(--paper2);font-family:var(--mono);text-transform:uppercase;letter-spacing:.06em;font-size:.78rem;color:var(--muted)}
.teams-intro h1{margin-bottom:.1em}

/* ============ SCENARIO DISTRIBUTION (Tally) ====================== */
.dist-card{padding:20px 22px}
.dist-legend{display:flex;gap:18px;flex-wrap:wrap;color:var(--muted);font-family:var(--mono);font-size:.66rem;
  margin-bottom:16px;align-items:center;text-transform:uppercase;letter-spacing:.08em}
.dist-legend .lg{display:inline-flex;align-items:center;gap:7px;font-weight:700}
.sw{width:13px;height:13px;display:inline-block;border:1px solid var(--ink)}
.seg-in{background:var(--c-in)}.seg-bub{background:var(--c-bub)}.seg-out{background:var(--c-out)}
.sw-tick{width:3px;height:14px;display:inline-block;background:var(--ink)}
.dist-advh{margin-left:auto;font-weight:800;color:var(--ink);font-size:.62rem;letter-spacing:.1em}
.dist{display:flex;flex-direction:column;gap:12px}
.dist-row{display:grid;grid-template-columns:170px 1fr 60px;align-items:center;gap:16px}
.dist-row.has-watched .dist-team{font-weight:800}
.dist-row.has-watched .dist-bar{box-shadow:0 0 0 1px var(--sig)}
.dist-team{min-width:0;overflow:hidden}
.dist-bar{display:flex;height:28px;overflow:hidden}
.dist-seg{display:flex;align-items:center;justify-content:center;min-width:0;transition:width .55s cubic-bezier(.3,.8,.3,1);border-right:1px solid var(--paper)}
.dist-seg:last-child{border-right:0}
.dist-seg .seg-lbl{font-family:var(--mono);font-size:.62rem;font-weight:800;letter-spacing:-.01em}
.seg-in.dist-seg{background:var(--c-in)}.seg-in.dist-seg .seg-lbl{color:var(--paper)}
.seg-bub.dist-seg{background:var(--c-bub)}.seg-bub.dist-seg .seg-lbl{color:var(--ink)}
.seg-out.dist-seg{background:var(--c-out)}.seg-out.dist-seg .seg-lbl{color:var(--ink2)}
.dist-adv{text-align:right;font-family:var(--mono);font-weight:800;font-size:1.05rem;font-variant-numeric:tabular-nums;color:var(--ink)}
.dist-adv .pct{font-size:.6em;color:var(--muted);margin-left:1px}
.dist-adv.hi{color:var(--vermilion)}.dist-adv.lo{color:var(--muted)}
.dist-note{margin:16px 2px 0;font-size:.84rem;line-height:1.6}
.dist-note b{font-weight:800}.k-in{color:var(--ink)}.k-bub{color:var(--ink2)}.k-out{color:var(--muted)}

/* ============ TEAM HERO (per-team accent block) ================== */
.team-hero{position:relative;overflow:hidden;color:var(--paper);background:var(--ink);border:2px solid var(--ink)}
.team-hero::before{content:"";position:absolute;left:0;top:0;bottom:0;width:14px;background:var(--accent)}
.th-inner{position:relative;z-index:1;display:flex;align-items:center;gap:26px;
  padding:clamp(24px,4vw,38px) clamp(24px,4vw,40px) clamp(24px,4vw,38px) clamp(34px,5vw,54px);flex-wrap:wrap}
.th-flag{font-size:4.4rem;line-height:1}
.th-main{flex:1;min-width:220px}
.th-eyebrow{font-size:.66rem;letter-spacing:.18em;color:var(--accent);margin-bottom:8px}
.team-hero h1{margin:0;font-size:var(--t-3xl);color:var(--paper);letter-spacing:-.03em;line-height:.92}
.th-line{margin:10px 0;color:rgba(244,242,236,.82);font-family:var(--mono);font-size:.82rem;text-transform:uppercase;letter-spacing:.04em}
.th-grp{box-shadow:inset 0 -2px 0 var(--accent);font-weight:800}
.th-grp:hover{color:var(--accent)}
.th-outlook{display:flex;align-items:center;gap:12px;margin-top:14px;flex-wrap:wrap}
.th-badge{font-size:.62rem;padding:5px 11px;background:transparent;color:var(--paper);border-color:rgba(244,242,236,.4)}
.th-badge.win{background:var(--accent);color:var(--ink);border-color:var(--accent)}
.th-outline{font-family:var(--mono);font-size:.74rem;color:rgba(244,242,236,.9);text-transform:uppercase;letter-spacing:.04em}
.th-watch{position:relative;z-index:1}
.th-watch .wl{background:transparent;border-color:rgba(244,242,236,.5);color:var(--paper)}
.th-watch .wl:hover{background:rgba(244,242,236,.12)}
.th-watch .wl.on{background:var(--accent);color:var(--ink);border-color:var(--accent)}

/* group banner ----------------------------------------------------- */
.group-banner{position:relative;overflow:hidden;display:flex;align-items:stretch;gap:0;border:2px solid var(--ink);background:var(--paper)}
.gb-letter{font-size:clamp(4rem,11vw,7.5rem);font-weight:800;line-height:1;display:flex;align-items:center;justify-content:center;
  padding:0 clamp(20px,4vw,42px);background:var(--ink);color:var(--paper);letter-spacing:-.04em}
.gb-main{padding:clamp(20px,3.5vw,32px) clamp(20px,4vw,34px);display:flex;flex-direction:column;justify-content:center;flex:1;min-width:0}
.gb-tag{font-size:.64rem;letter-spacing:.18em;color:var(--vermilion);margin-bottom:6px}
.gb-title{margin:0 0 8px;color:var(--ink);font-size:var(--t-2xl);letter-spacing:-.03em;line-height:.95}
.gb-state{font-family:var(--mono);font-weight:700;color:var(--ink2);margin-bottom:14px;text-transform:uppercase;font-size:.78rem;letter-spacing:.04em}
.gb-teams{display:flex;flex-wrap:wrap;gap:8px}
.gb-teams .team{background:var(--paper2);border:1px solid var(--line);color:var(--ink);font-weight:700}
.gb-teams .team:hover{background:var(--paper3)}

/* ============ ROAD-TO-THE-FINAL (branch graph) =================== */
.roads{display:grid;grid-template-columns:1fr 1fr;gap:var(--s4)}
.road-blurb{margin:2px 0 14px;font-size:1.02rem;line-height:1.6;color:var(--ink);max-width:64ch;
  border-left:3px solid var(--vermilion);padding-left:14px}
.road-intro{margin:-8px 0 var(--s5);font-size:.88rem;color:var(--ink2)}
.road-line{background:var(--paper);border:2px solid var(--ink);padding:18px 20px}
.road-line.third{grid-column:1/-1}
.road-line-head{display:flex;align-items:center;gap:10px;margin-bottom:16px;flex-wrap:wrap;padding-bottom:10px;border-bottom:1px solid var(--line)}
.road-line-head h4{margin:0;font-size:1rem}
.road-track{font-size:.58rem;letter-spacing:.1em;padding:3px 9px;background:var(--vermilion);color:var(--on-accent)}
.road-track.alt{background:var(--ink);color:var(--paper)}
.road-sub{margin:-8px 0 14px;font-size:.82rem;color:var(--ink2)}
.road-graph{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:0}
.road-step{position:relative;display:grid;grid-template-columns:92px 22px 1fr;align-items:center;gap:10px;padding:11px 0;min-height:48px}
.road-step+.road-step{border-top:1px dashed var(--line)}
.road-node{display:flex;flex-direction:column;gap:3px}
.road-rd{display:inline-grid;place-items:center;min-width:46px;height:24px;padding:0 9px;background:var(--ink);color:var(--paper);font-size:.66rem;font-weight:800;width:fit-content;letter-spacing:.06em}
.road-date{font-family:var(--mono);font-size:.62rem;color:var(--muted)}
/* keep the kickoff inside its column — wrap day/time instead of spilling onto the connector */
.road-date .ko{flex-wrap:wrap;white-space:normal;gap:0 .6ch}
.road-date .ko-day,.road-date .ko-time{white-space:nowrap}
.road-branch{position:relative;align-self:stretch;width:22px}
.road-branch::before{content:"";position:absolute;left:50%;top:0;bottom:0;width:2px;transform:translateX(-50%);background:var(--vermilion);opacity:.5}
.road-branch::after{content:"";position:absolute;left:50%;top:50%;width:11px;height:2px;background:var(--vermilion);transform:translateY(-50%)}
.road-branch.single::before{background:var(--line2)}
.road-step[data-cands="1"] .road-branch::after,.road-step .road-branch.single::after{background:var(--line2)}
.road-opp{display:flex;align-items:center;gap:9px;min-width:0;flex-wrap:wrap}
.road-vs{font-size:.58rem;color:var(--muted);letter-spacing:.12em}
.road-fan{display:flex;flex-wrap:wrap;gap:6px;min-width:0;position:relative}
.road-fan.multi{padding:4px 0}
.road-cand .cand{font-size:.72rem}
.road-cand.resolved .cand{background:var(--paper);border-color:var(--ink);font-weight:800}
.road-more{display:inline-grid;place-items:center;font-family:var(--mono);font-size:.64rem;font-weight:800;color:var(--muted);border:1px dashed var(--line2);padding:2px 7px}
.road-step.has-watched .road-rd{background:var(--vermilion);color:var(--on-accent)}

/* ============ BRACKET (one fixed tree, right-angle connectors) ====
   Every box is the SAME fixed size, every column the same height, and each
   column's matches are distributed with `space-around` — which makes match i of
   round R land exactly at the midpoint of matches 2i / 2i+1 of round R-1, in
   pure CSS, no measurement. JS only paints the connector strokes and toggles the
   edge fades. Horizontal overflow scrolls the inner wrap; the fades live on the
   non-scrolling frame so they pin to the visible edges (never drift mid-column).*/
.bracket-intro h1{margin-bottom:.1em}
.bracket-rail{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:16px}
.brn-label{font-family:var(--mono);font-weight:800;font-size:.62rem;letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
.bracket-rail-nav{display:flex;gap:0;border:2px solid var(--ink);width:fit-content;max-width:100%;overflow:hidden}
.brn-item{font-family:var(--mono);font-weight:800;font-size:.66rem;letter-spacing:.1em;text-transform:uppercase;
  padding:7px 13px;color:var(--muted);border-right:1px solid var(--line);background:var(--paper);white-space:nowrap}
.brn-item:last-child{border-right:0}
.brn-item.on{background:var(--ink);color:var(--paper)}
.bracket-frame{position:relative;border:2px solid var(--ink);background:var(--paper);overflow:hidden}
.bracket-wrap{overflow-x:auto;overflow-y:hidden;-webkit-overflow-scrolling:touch}
.bz-edge-l,.bz-edge-r{position:absolute;top:0;bottom:0;width:40px;z-index:6;pointer-events:none;transition:opacity .2s}
.bz-edge-l{left:0;background:linear-gradient(90deg,var(--paper),rgba(244,242,236,0))}
.bz-edge-r{right:0;background:linear-gradient(270deg,var(--paper),rgba(244,242,236,0))}
.bracket-frame.at-start .bz-edge-l{opacity:0}
.bracket-frame.at-end .bz-edge-r{opacity:0}
.kbracket{--km-h:84px;position:relative;display:flex;gap:clamp(22px,3.4vw,56px);
  min-width:1120px;padding:16px 22px 24px;min-height:calc(var(--km-h) * 16 + 270px)}
.bz-layer{position:absolute;inset:0;z-index:0;pointer-events:none;overflow:visible}
.bz-link{stroke:var(--line2);stroke-width:1.6;fill:none}
.bz-link[data-watched]{stroke:var(--vermilion);stroke-width:2.4}
.kr-col{position:relative;z-index:1;flex:1 1 0;min-width:196px;display:flex;flex-direction:column}
.kr-head{flex:0 0 auto;display:flex;align-items:center;gap:8px;height:30px;font-size:.66rem;color:var(--ink);
  margin-bottom:12px;padding-bottom:8px;border-bottom:2px solid var(--ink)}
.kr-body{flex:1 1 auto;position:relative}
.kr-count{margin-left:auto;font-family:var(--mono);font-size:.6rem;color:var(--paper);background:var(--ink);padding:1px 8px}
/* Boxes size to their content (so a deep round can show every candidate flag);
   JS then centres each one between its two feeders. min-height keeps the early,
   short boxes from looking cramped. */
.km{position:relative;min-height:var(--km-h);box-sizing:border-box;background:var(--paper);
  border:1.5px solid var(--ink);padding:8px 10px;margin:0 0 10px;display:flex;flex-direction:column;
  justify-content:flex-start;gap:4px;transition:background .14s}
.km:hover{background:var(--paper2)}
.km.has-watched{box-shadow:inset 5px 0 0 var(--sig)}
.km-live{border-color:var(--vermilion);border-width:2px}
.km-when{font-family:var(--mono);font-size:.55rem;line-height:1.1;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.km-when .ko-day{color:var(--ink2)}
.km-line{position:relative;height:1px;background:var(--line);margin:3px 0}
.km-wire{position:absolute;right:-1px;top:50%;transform:translateY(-50%);opacity:0}
.km-live .km-wire{opacity:1}
.km-live .km-wire .wire-pulse{width:7px;height:7px}
.km-team{display:flex;align-items:center;gap:5px;min-width:0;min-height:24px;font-size:.84rem;line-height:1.4}
.km-team.is-candidate{align-items:center}
.km-team .bteam{min-width:0;font-weight:700}
.km-team .bteam .nm{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.km-team.is-candidate{color:var(--muted)}
.km-team .bteam.prov{color:var(--ink2);font-weight:600}
.bcode{font-family:var(--mono);font-size:.56rem;color:var(--muted);background:var(--paper2);border:1px solid var(--line);padding:0 5px;margin-left:3px;white-space:nowrap}
/* Candidate flags. Colour-emoji glyphs (notably Apple Color Emoji on macOS)
   render TALLER than their line box, so each row gets an explicit, roomy height
   and the flag is flex-centred inside it — the row fully contains the glyph, the
   box measures and grows correctly, and nothing spills over the date above. */
.bcands{display:flex;flex-wrap:wrap;align-items:center;gap:5px 8px;min-width:0;line-height:1.4}
.bcands .bcand{display:inline-flex;align-items:center;gap:4px;font-size:.78rem;min-width:0;min-height:24px;line-height:1.4}
.bcands .bcand .nm{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:78px}
.bcands.many{gap:5px 8px}
.bcands.many .bcand{height:26px;justify-content:center;line-height:1;font-size:1rem}
.bcands.many .bcand .nm{display:none}          /* >2 possible: a row of flags */
.bcands.many .bcand .fl{font-size:1.05em;line-height:1;display:block}
.bslot{font-family:var(--mono);color:var(--muted);font-size:.74rem;font-weight:600}
.km-g{margin-left:auto;font-family:var(--mono);font-weight:800;font-variant-numeric:tabular-nums;min-width:16px;text-align:right}
.km-g.kloss{color:var(--muted)}.km-g.kwin{color:var(--ink)}
.km-team .bteam.win,.km-team:has(.kwin) .bteam{color:var(--ink);font-weight:800}
/* The plinth is positioned by JS directly beneath the final match box. */
.champion-plinth{position:relative;text-align:center;padding:18px 14px 16px;border:2px solid var(--ink);background:var(--ink);color:var(--paper)}
.champion-plinth::before{content:"";position:absolute;left:0;right:0;top:0;height:8px;background:var(--vermilion)}
.cp-trophy{filter:invert(1)}
.cp-lbl{font-size:.62rem;letter-spacing:.14em;color:var(--vermilion);margin:8px 0 8px}
.champ-name{display:inline-flex;align-items:center;gap:8px;font-weight:800;font-size:1.05rem;color:var(--paper)}
.champ-name .fl{font-size:1.3em}
.champ-name.pending{font-family:var(--mono);font-weight:700;font-size:.8rem;color:rgba(244,242,236,.7);text-transform:uppercase;letter-spacing:.06em}
.champ-name.watched{color:var(--vermilion)}
/* Narrow screens: a plain stacked list of columns, no connector geometry. */
/* Phones: keep the real tree (columns + connectors + watched highlights), but
   make each column ~one screen wide with a peek of the next, and snap-scroll
   column-by-column so a swipe always lands a column flush to the left edge (the
   far-right column lands flush right). JS opens on the current round. */
@media(max-width:720px){
  .kbracket{min-width:0;gap:16px;padding:14px 14px 22px}
  .kr-col{flex:0 0 82vw;min-width:0;scroll-snap-align:start}
  .kr-col:last-child{scroll-snap-align:end}
  .bracket-wrap{scroll-snap-type:x mandatory;scroll-padding-left:14px;
    overscroll-behavior-x:contain}
  .km{min-height:72px}
}

/* ============ CALENDAR ============================================ */
.cal-intro h1{margin-bottom:.1em}
.cal-grid{margin-top:6px}
.cal-dow-row{display:grid;grid-template-columns:repeat(7,1fr);gap:8px;margin-bottom:8px}
.cal-dow-h{font-family:var(--mono);font-size:.6rem;font-weight:800;letter-spacing:.12em;
  text-transform:uppercase;color:var(--muted);text-align:center;padding-bottom:4px;border-bottom:2px solid var(--ink)}
.cal-week{display:grid;grid-template-columns:repeat(7,1fr);gap:8px;margin-bottom:8px}
.cal-day{border:1.5px solid var(--line2);background:var(--paper);min-height:96px;padding:7px 8px;display:flex;flex-direction:column;gap:6px}
.cal-day.empty{border-style:dashed;border-color:var(--line);background:transparent}
.cal-day.today{border-color:var(--vermilion);border-width:2px;box-shadow:inset 0 3px 0 var(--vermilion)}
.cal-d-head{display:flex;align-items:baseline;gap:5px;font-family:var(--mono)}
.cal-dow{font-size:.58rem;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.cal-dom{font-size:1rem;font-weight:800;color:var(--ink);font-variant-numeric:tabular-nums}
.cal-mon{font-size:.58rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
.cal-day.today .cal-dom{color:var(--vermilion)}
.cal-d-body{display:flex;flex-direction:column;gap:6px}
.cal-m{border-left:2px solid var(--line2);padding:2px 0 2px 7px}
.cal-m.is-done{border-left-color:var(--ink)}
.cal-m.is-live{border-left-color:var(--vermilion)}
/* a pinned team plays in this match — light it up */
.cal-m.has-watched{background:rgba(255,59,20,.06);border-left-color:var(--ink);outline:2px solid var(--ink);outline-offset:-1px}
.cal-m-head{display:flex;align-items:center;flex-wrap:wrap;gap:2px 6px;margin-bottom:2px}
.cal-tag{font-family:var(--mono);font-size:.5rem;font-weight:800;letter-spacing:.06em;text-transform:uppercase;
  color:var(--paper);background:var(--ink2);padding:0 4px}
.cal-time{font-family:var(--mono);font-size:.62rem;font-weight:800;color:var(--ink);font-variant-numeric:tabular-nums}
.cal-tz{color:var(--vermilion);margin-left:1px;font-size:.85em}
.cal-score{font-family:var(--mono);font-size:.66rem;font-weight:800;color:var(--ink);font-variant-numeric:tabular-nums}
.cal-m.is-live .cal-time,.cal-m.is-live .cal-score{color:var(--vermilion)}
.cal-m.is-done .cal-time{font-weight:600;color:var(--muted)}  /* time = context; score leads on a played match */
.cal-m-teams{display:flex;flex-direction:column;gap:1px;font-size:.72rem;min-width:0}
.cal-side{display:flex;align-items:center;min-width:0}
.cal-side .cal-tm{font-weight:700;gap:4px;padding:0;min-width:0}
.cal-side .cal-tm .nm{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cal-cands{display:inline-flex;flex-wrap:wrap;gap:2px 6px;min-width:0}
.cal-cands .cand .nm{font-weight:600;color:var(--ink2)}
.cal-tbd{font-family:var(--mono);font-size:.62rem;color:var(--muted)}
.cal-v{font-size:.5rem;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin:0 0 0 1px}
.cal-m.is-done .cal-side{opacity:.82}
/* Phones: drop the 7-up grid for a single-column agenda (skip empty days). */
@media(max-width:760px){
  .cal-dow-row{display:none}
  .cal-week{grid-template-columns:1fr;gap:0;margin-bottom:0}
  .cal-day{border-width:0 0 1.5px 0;min-height:0;border-bottom:1.5px solid var(--line)}
  .cal-day.empty{display:none}
  .cal-day.today{border:2px solid var(--vermilion)}
  .cal-d-head{position:sticky}
  /* lay the day's matches two across instead of a single stacked column */
  .cal-d-body{display:grid;grid-template-columns:1fr 1fr;gap:8px 12px;align-items:start}
}

/* footer ----------------------------------------------------------- */
.site-foot{max-width:var(--maxw);margin:0 auto;padding:0 clamp(14px,4vw,28px) var(--s8);position:relative;z-index:1}
.foot-rule{height:3px;background:var(--ink);margin-bottom:0}
.foot-grid{display:grid;grid-template-columns:2fr 1fr 1fr;border-bottom:2px solid var(--ink)}
.foot-cell{padding:18px 18px;border-right:1px solid var(--line)}
.foot-cell:last-child{border-right:0}
.foot-brand{display:flex;flex-direction:column;gap:6px;padding-left:0}
.foot-wm{font-family:var(--mono);font-weight:800;font-size:1rem;letter-spacing:.1em;color:var(--ink)}
.foot-yr{color:var(--vermilion)}
.foot-sub{font-family:var(--mono);font-size:.66rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
.foot-stat{display:flex;flex-direction:column;gap:6px}
.foot-k{font-family:var(--mono);font-size:.6rem;letter-spacing:.16em;color:var(--muted)}
.foot-v{font-family:var(--mono);font-weight:800;font-size:.92rem;color:var(--ink);display:inline-flex;align-items:center;gap:8px}
.upd-dot{display:inline-flex}.upd-dot .wire-pulse{width:8px;height:8px}
.foot-fine{font-family:var(--mono);font-size:.64rem;line-height:1.7;color:var(--muted);max-width:780px;margin-top:16px;letter-spacing:.02em}
.foot-tz{display:flex;align-items:center;justify-content:flex-end;flex-wrap:wrap;gap:9px;margin-top:14px;font-family:var(--mono)}
.foot-tz-k{font-size:.58rem;font-weight:800;letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}
.tz-select{font-family:var(--mono);font-size:.7rem;font-weight:700;color:var(--ink);background-color:var(--paper);
  border:1.5px solid var(--ink);padding:5px 26px 5px 9px;cursor:pointer;letter-spacing:.02em;border-radius:0;
  -webkit-appearance:none;appearance:none;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M1 1l4 4 4-4' fill='none' stroke='%2313110d' stroke-width='1.6'/%3E%3C/svg%3E");
  background-repeat:no-repeat;background-position:right 9px center}
.tz-select:hover{background-color:var(--paper2)}
.tz-select:focus-visible{outline:2px solid var(--vermilion);outline-offset:2px}

/* cols (team page fixtures) ----------------------------------------- */
.cols{display:grid;grid-template-columns:1fr 1fr;gap:var(--s5)}
.col-h{font-size:var(--t-lg)}

/* ============ RESPONSIVE ========================================= */
@media(max-width:880px){
  .roads{grid-template-columns:1fr}
  .foot-grid{grid-template-columns:1fr 1fr}
  .foot-brand{grid-column:1/-1;border-right:0;border-bottom:1px solid var(--line)}
}
@media(max-width:760px){
  main{padding:var(--s4) clamp(12px,4vw,18px) var(--s7)}
  section{margin:var(--s7) 0}
  .cols{grid-template-columns:1fr;gap:var(--s4)}
  .group-grid{grid-template-columns:1fr}
  .hero-strip{flex-wrap:wrap}
  .hs-cell{flex:1 0 44%;border-right:1px solid var(--line);border-bottom:1px solid var(--line);padding:10px 12px}
  .hs-host{margin-left:0;text-align:left;align-items:flex-start}
  .hero-foot{flex-direction:column;align-items:stretch;gap:20px}
  .hero-next{border-left:0;border-top:2px solid var(--ink);padding-left:0;padding-top:16px;max-width:100%}
  .site-nav a{padding:0 12px;font-size:.68rem}
  .brand a{gap:9px;padding:11px 14px}
  .wm-l1,.wm-l2{font-size:.7rem}
  .team-hero .th-inner{flex-direction:column;text-align:center;padding:28px 20px}
  .team-hero::before{width:100%;height:10px;bottom:auto}
  .th-outlook{justify-content:center}
  .group-banner{flex-direction:column}
  .gb-letter{padding:14px;font-size:clamp(3.4rem,16vw,4.6rem)}
  .gb-main{text-align:center;align-items:center}
  .gb-teams{justify-content:center}
  .standings .hide-s{display:none}
  .standings th,.standings td{padding:8px 6px}
  /* keep team names on one line on phones; give the odds tally just enough room */
  .standings .tm{white-space:nowrap}
  .group-card.solo .standings .tm .nm{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:34vw;display:inline-block;vertical-align:middle}
  .standings td.odds,.standings td.race{min-width:74px;white-space:nowrap}
  .standings td.odds .mini-tally,.standings td.race .mini-tally{width:34px;min-width:34px}
  .standings .odds-n{margin-left:3px;font-size:.66rem}
  /* solo standings can scroll horizontally if truly cramped (wrap already clips) */
  .group-card.solo{overflow-x:auto}
  .dist-row{grid-template-columns:100px 1fr 46px;gap:9px}
  .road-step{grid-template-columns:74px 18px 1fr}
  .road-rd{min-width:40px;font-size:.6rem}
  .yt-empty{flex-direction:column;text-align:center;gap:14px;padding:26px 20px}
  .yt-empty-body{align-items:center}
  .nm,.tcard-name,.m-side .nm,.pz-team .nm{white-space:normal;overflow:visible;text-overflow:clip;word-break:break-word;min-width:0}
  /* the thirds table carries the extra Race-to-8th column; on WebKit (iPhone
     Chrome/Safari) that compresses the team cell until names break one letter
     per line. Keep names whole and let .thirds-card scroll instead. */
  .thirds .tm .nm{white-space:nowrap;word-break:normal;overflow:visible}
  .m-side{min-width:0}
  .m-row{gap:8px}
  .pz-grp{max-width:none}
  .sec-head .muted{margin-left:0;text-align:left}
}
/* Mobile: the Pulse ribbon stacks vertically (still time-ordered, one divider). */
@media(max-width:560px){
  .pulse-band{flex-wrap:wrap;overflow-x:visible}
  .pz{flex:1 1 100%;border-right:0;border-bottom:1px solid var(--line)}
  .now-divider{flex:1 1 100%;flex-direction:row;align-self:auto;padding:8px 0;gap:10px}
  .now-lbl{writing-mode:horizontal-tb;transform:none}
  /* 4-item nav: collapse the brand to just the mark so the tabs fit */
  .wm-text{display:none}
  .site-nav a{padding:0 9px;font-size:.6rem;letter-spacing:.03em}
}
@media(prefers-reduced-motion:reduce){
  *{animation:none!important;transition:none!important;scroll-behavior:auto!important}
  .wire-pulse{box-shadow:none}
  .ht-live::before{transform:scaleX(1)!important}
  [data-reveal]{opacity:1!important;transform:none!important}
}
"""

# Cache-busting fingerprint for the CSS/JS assets. The HTML links them as
# style.css?v=<ASSET_VER> / app.js?v=<ASSET_VER>; when either asset changes the
# version changes, so returning visitors fetch the new file instead of a stale
# cached one. Referenced by shell().
ASSET_VER = hashlib.sha256((STYLE + APP_JS).encode("utf-8")).hexdigest()[:10]
