"""Shared HTML fragment builders: team links, watch buttons, slot chips,
W/L/D badges, standings tables, scenario distribution bars, match lines, the
Pulse band, team cards, and the ordinal/round-label helpers several pages share.
"""
from __future__ import annotations

from datetime import timedelta

from . import bracket, config, data, util, venues
from .flags import flag
from .times import (E, PT_LABEL, _epoch, _pt_datetime, _pt_parts, _utc_iso,
                    kickoff_label, today_pt)


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

# code -> the CSS word suffix on a match side. The single source for the W/L/D
# class fragment shared by match_line, the Pulse band and the calendar.
_WL_CLASS = {"w": " won", "l": " lost", "d": " drew"}


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
    by_num = ctx.by_num
    t1 = bracket.resolve_slot(m["team1"], ctx.analyses, by_num)
    t2 = bracket.resolve_slot(m["team2"], ctx.analyses, by_num)
    done = data.has_result(m)
    win = bracket.match_winner(m) if done else None
    r1, r2 = side_result(done, t1["team"], win), side_result(done, t2["team"], win)
    w1, w2 = _WL_CLASS.get(r1, ""), _WL_CLASS.get(r2, "")
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


def _pulse_card(ctx, m, kind):
    """One Pulse-ribbon card — a compact scorebug for a single match. `kind` is
    'done' (final score + scorers) or 'up' (kickoff time). Carries the shared
    data-live / data-ts / data-live-mid / data-live-tag hooks so the generalised
    live poller lights it in place. Shared by the Matchday-Pulse band and the
    knockout-mode current-round ribbon (reflow, don't reinvent)."""
    by_num = ctx.by_num
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
        w1 = _WL_CLASS[side_result(True, t1["team"], win)]
        w2 = _WL_CLASS[side_result(True, t2["team"], win)]
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
        badge = wl_badge({v: k for k, v in _WL_CLASS.items()}.get(wc, ""))
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


def pulse_band(ctx):
    """The signature "Pulse" band: a single time-ordered ribbon fusing the latest
    results and the next kickoffs, with exactly one "now" divider between them.

    Cards carry data-ts (monotonic non-decreasing), venue, scorers (done) or
    kickoff (upcoming). The divider IS the Live Wire signal element (.now-divider
    + .wire-pulse), shared with the bracket's live edge and the watched glow.
    """
    # A tight "now" window: yesterday + today behind us, today + tomorrow ahead —
    # the pulse is about what just happened and what's next, not the whole schedule.
    today = today_pt()
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

    done_cards = "".join(_pulse_card(ctx, m, "done") for m in done)
    up_cards = "".join(_pulse_card(ctx, m, "up") for m in up)
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
    by_num = ctx.by_num
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


def _card_status(ctx, team):
    """Tournament-status meta for a watchlist card (knockout / champion mode),
    mirroring the team-hero language so a pinned team reads the same everywhere:
      alive  -> the round it is playing next (e.g. "Quarter-final")
      out    -> "Out · <round> · v <opponent>" (group stage or the game it lost)
      champ  -> "World champions" / "Runners-up"
    Returns (inner_html, tone) with tone in {'alive','out','champ',''}."""
    final_m = next((m for m in ctx.matches if m.get("round") == "Final"), None)
    if final_m is not None and data.has_result(final_m):
        if bracket.match_winner(final_m) == team:
            return ("<span>World champions</span>", "champ")
        if bracket.match_loser(final_m) == team:
            return ("<span>Runners-up</span>", "out")
    nm = ctx.next_match(team)
    if nm is not None:
        m, _opp, rd = nm
        proj = ctx.projections[team]
        is_group = str(rd).startswith("Matchday")
        # A team that has finished its group but whose group isn't settled only
        # projects SPECULATIVELY forward — don't claim a knockout round yet.
        if is_group or not proj["group_complete"]:
            return ("<span>Group stage</span>", "alive")
        return (f'<span>{E(_round_full(rd))}</span>', "alive")
    if ctx.knocked_out(team):
        return ('<span>Out</span> · <span>group stage</span>', "out")
    _, recent = ctx.team_fixtures(team)
    if recent is not None:
        rd_short = _round_short(recent.get("round", ""))
        opp = recent.get("team2") if recent.get("team1") == team else recent.get("team1")
        # This meta sits INSIDE the card's .tcard-main <a>, so the opponent must be
        # a plain chip (data-team keeps the watched glow) — a nested <a> is invalid
        # and the browser drops it, losing the opponent.
        opp_html = (f'<span class="team tcs-opp" data-team="{E(opp)}">'
                    f'<span class="fl">{flag(opp)}</span><span class="nm">{E(opp)}</span></span>'
                    if opp else "TBD")
        return (f'<span>Out</span> · <span>{E(rd_short)}</span> · v {opp_html}', "out")
    return ("", "")


def team_card(ctx, team, rich=False, status=False):
    """A watchlist card. `status=True` swaps the group-position meta ("Group A ·
    1st · 9 pts") for a live tournament-status line — used on the phase-aware home
    once the group stage is settled, so a pinned team leads with where it IS in
    the knockouts rather than a frozen group standing."""
    proj = ctx.projections[team]
    pr, sec = util.accent(team)
    rec = proj["row"]
    fixtures = _tcard_fixtures(ctx, team) if rich else ""
    if status:
        st_html, tone = _card_status(ctx, team)
        meta = (f'<span class="tcard-meta tcard-status {tone}">{st_html}</span>'
                if st_html else "")
    else:
        meta = (f'<span class="tcard-meta muted">{E(proj["group"])} · '
                f'{_ordinal(proj["rank"])} · {rec["Pts"]} pts</span>')
    return (
        f'<div class="tcard{" rich" if rich else ""}" data-team-card="{E(team)}" data-team="{E(team)}" '
        f'style="--accent:{pr};--accent2:{sec}">'
        f'<div class="tcard-top">'
        f'<a class="tcard-main" href="{util.page_for(team)}">'
        f'<span class="tcard-flag">{flag(team)}</span>'
        f'<span class="tcard-body"><span class="tcard-name">{E(team)}</span>'
        f'{meta}</span>'
        f'</a>{star_icon(team)}</div>'
        f'{fixtures}</div>'
    )


# The short round labels (R32/R16/QF/SF/F) come straight from the one config map;
# the bracket rail, fantasy and betting emit them verbatim.
_FB_RND = config.KO_SHORT

# Ordinal helper now lives in util (shared with the blurbs pipeline).
_ordinal = util.ordinal


def _round_short(rd):
    """config.KO_SHORT, but spelling the Final out in full (only the bracket rail
    wants the bare 'F')."""
    if rd == "Final":
        return "Final"
    return config.KO_SHORT.get(rd, rd)


# Full round labels for the phase-aware home (hero line, scorebug, section heads).
# Multi-match rounds read as plurals ("Quarter-finals"); the bronze match uses its
# stage name. Every value here already has pt-BR coverage in wc/i18n.py.
_ROUND_FULL = {
    "Round of 32": "Round of 32",
    "Round of 16": "Round of 16",
    "Quarter-final": "Quarter-finals",
    "Semi-final": "Semi-finals",
    "Match for third place": "Third-place match",
    "Final": "Final",
}


def _round_full(rd):
    return _ROUND_FULL.get(rd, rd)


def _slot_name(res, cls=""):
    """A bracket slot as a team chip (resolved nation, reusing the .team device so
    a pinned side still glows) or a terse placeholder — the compact form used by
    the hero line and the home bracket rail."""
    if res["team"]:
        return team_link(res["team"], f"team {cls}".strip())
    return f'<span class="{cls} tbd muted">{E(res["label"])}</span>'


# --------------------------------------------------------------------------
# Phase-aware home builders (knockout / champion mode). The hero, Your-teams,
# groups grid and thirds race live in wc/pages/home.py; these are the shared
# fragments the knockout layout is assembled from.
# --------------------------------------------------------------------------
def scorebug(ctx, m):
    """A large broadcast scorebug for the next (or in-play) knockout match. Scales
    up the .pz card language — flags, mono kickoff, W/L tag — and carries the same
    data-live / data-ts / data-live-mid / data-live-tag hooks, so the generalised
    live poller lights it the moment the match kicks off (no bespoke wiring)."""
    by_num = ctx.by_num
    t1 = bracket.resolve_slot(m["team1"], ctx.analyses, by_num)
    t2 = bracket.resolve_slot(m["team2"], ctx.analyses, by_num)
    done = data.has_result(m)
    win = bracket.match_winner(m) if done else None
    r1, r2 = side_result(done, t1["team"], win), side_result(done, t2["team"], win)
    rd_lbl = _round_full(m.get("round", ""))
    venue_stadium, _v = venues.venue(m.get("ground", ""))
    pt_day, pt_time = _pt_parts(m)
    utc = _utc_iso(m)
    date_attr = f' data-utc="{utc}" data-tfmt="day"' if (pt_day and utc) else ""
    if done:
        g1, g2 = data.final_score(m)
        pens = (m.get("score") or {}).get("p")
        pen_html = f'<span class="sb-pens">{pens[0]}–{pens[1]} pens</span>' if pens else ""
        figure = (f'<div class="sb-figure sb-score" data-live-mid>'
                  f'<b class="sg{" win" if r1=="w" else ""}">{g1}</b><span class="sdash">–</span>'
                  f'<b class="sg{" win" if r2=="w" else ""}">{g2}</b></div>{pen_html}')
        tag = '<span class="pz-tag done" data-live-tag>FT</span>'
    else:
        ko = (f'{E(pt_time)}<span class="pz-tz tz">{PT_LABEL}</span>') if pt_time else "TBD"
        ko_attr = f' data-utc="{utc}" data-tfmt="time"' if (pt_time and utc) else ""
        figure = f'<div class="sb-figure sb-ko" data-live-mid{ko_attr}>{ko}</div>'
        tag = '<span class="pz-tag up" data-live-tag>Kicks off</span>'
    live = bool(t1["team"] and t2["team"])
    live_attr = f' data-live data-date="{E(m.get("date",""))}"' if live else ""

    def sbteam(res, code, is_b=False):
        t = res["team"]
        inner = (f'<span class="fl">{flag(t) if t else "·"}</span>'
                 f'<span class="nm">{E(t or res["label"])}</span>')
        badge = wl_badge(code)
        body = (badge + inner) if is_b else (inner + badge)
        cls = "sb-team" + (" b" if is_b else "") + (_WL_CLASS.get(code, ""))
        if t:
            return f'<a class="{cls}" data-team="{E(t)}" href="{util.page_for(t)}">{body}</a>'
        return f'<div class="{cls}" data-team="">{body}</div>'
    return (
        f'<div class="scorebug {"is-done" if done else "is-upcoming"}" '
        f'data-ts="{_epoch(m)}"{live_attr}>'
        f'<div class="sb-head"><span class="sb-rd">{E(rd_lbl)}</span>{tag}'
        f'<span class="sb-date muted"{date_attr}>{E(pt_day or "")}</span></div>'
        f'<div class="sb-row">{sbteam(t1, r1)}<div class="sb-mid">{figure}</div>'
        f'{sbteam(t2, r2, is_b=True)}</div>'
        f'<div class="sb-foot muted">{E(venue_stadium)}</div></div>'
    )


def round_ribbon(ctx, matches):
    """The rest of the current knockout round beside the scorebug — the same Pulse
    ribbon device (each card live-wired), reflowed as a round schedule."""
    if not matches:
        return ""
    cards = "".join(_pulse_card(ctx, m, "done" if data.has_result(m) else "up")
                    for m in matches)
    return f'<div class="pulse-band ko-sched" data-band="ko-round">{cards}</div>'


def _rail_slot(res):
    """A compact rail slot: the resolved nation, its ≤2 candidate names, ≤4
    candidate flags, or a terse count — never a "Winner of M…" token, matching
    the bracket page's slot device (the connectors, not jargon, carry structure)."""
    if res["team"]:
        return team_link(res["team"], "team krl-tm")
    cands = sorted(res.get("candidates") or [])
    if not cands:
        return '<span class="krl-tm tbd muted">TBD</span>'
    if len(cands) <= 2:
        inner = '<span class="krl-slash" aria-hidden="true">/</span>'.join(
            team_link(c, "team krl-cand") for c in cands)
        return f'<span class="krl-cands">{inner}</span>'
    if len(cands) <= 4:
        flags = "".join(f'<span class="krl-fl" data-team="{E(c)}" title="{E(c)}">{flag(c)}</span>'
                        for c in cands)
        return f'<span class="krl-cands flags">{flags}</span>'
    return f'<span class="krl-tm tbd muted">{len(cands)} possible</span>'


def _rail_side(r, key):
    """One side of a compact bracket-rail tie: the slot plus, for a played tie, its
    goal count and winner emphasis (reusing the km W/L read)."""
    res = r[key]
    code = side_result(r["played"], res["team"], r["winner"])
    g = ""
    if r["played"]:
        g1, g2 = data.final_score({"score": r["score"]})
        gv = g1 if key == "team1" else g2
        g = f'<span class="krl-g{" kw" if code == "w" else ""}">{gv}</span>'
    cls = "krl-side" + (" b" if key == "team2" else "")
    cls += (" kw" if code == "w" else (" kl" if r["played"] else ""))
    return f'<span class="{cls}">{_rail_slot(res)}{g}</span>'


def bracket_rail(ctx, current_round):
    """A compact horizontal bracket summary: the current round's ties, then the
    path to the final as slot chips (candidate fans until each tie resolves),
    linking out to the full connected tree on bracket.html. Reuses the bracket
    slot device rather than reinventing it."""
    main = [(rd, rows) for rd, rows in ctx.bracket if rd in config.KO_ROUNDS]
    if not main:
        return ""
    # Anchor on the current MAIN round (the bronze match rides with the Final).
    anchor = current_round if current_round in config.KO_ROUNDS else "Final"
    start = next((i for i, (rd, _) in enumerate(main) if rd == anchor), 0)
    cols = []
    for rd, rows in main[start:]:
        ties = "".join(
            f'<div class="krl-tie{" is-done" if r["played"] else ""}">'
            f'{_rail_side(r, "team1")}{_rail_side(r, "team2")}</div>'
            for r in rows)
        cur = " krl-cur" if rd == anchor else ""
        cols.append(f'<div class="krl-col{cur}"><div class="krl-h">{E(config.KO_SHORT[rd])}</div>'
                    f'<div class="krl-ties">{ties}</div></div>')
    champ = _champion(ctx)
    if champ:
        cap = (f'<div class="krl-champ-tm">{team_link(champ, "krl-tm")}</div>')
    else:
        cap = '<div class="krl-champ-tm pending muted">Champion T.B.D.</div>'
    cols.append(
        '<div class="krl-col krl-champ">'
        '<div class="krl-h"><img class="krl-trophy" src="assets/trophy.svg" alt="" '
        'width="14" height="14" aria-hidden="true">World Champion</div>'
        f'{cap}</div>')
    return f"""
<section class="ko-rail-sec" data-reveal aria-label="Bracket">
  <div class="sec-head"><h2>The bracket</h2>
    <a class="sec-link" href="bracket.html">Full bracket <span class="arrow" aria-hidden="true">→</span></a></div>
  <div class="ko-rail-frame"><div class="ko-rail" data-hscroll>{"".join(cols)}</div></div>
</section>
"""


def archive_band(ctx):
    """The settled group stage as one compact archive strip — one row per group:
    the letter (linking to its page), the two qualifiers, and the best-third if
    that group's third-placed side made the bracket. The full tables live on the
    group pages; the home stops re-printing twelve of them once the stage is done."""
    rows = []
    for g in sorted(ctx.analyses):
        info = ctx.analyses[g]
        letter = info["group"].split()[-1]
        table = info["table"]
        chips = []
        for i, row in enumerate(table[:2], 1):
            chips.append(f'<span class="ga-team">{team_link(row["team"], "ga-tm")}'
                         f'<span class="ga-pos">{i}</span></span>')
        third = table[2] if len(table) >= 3 else None
        if third and third["team"] in ctx.advanced:
            chips.append(f'<span class="ga-team ga-third">{team_link(third["team"], "ga-tm")}'
                         f'<span class="ga-badge">3rd</span></span>')
        href = f"group-{letter.lower()}.html"
        rows.append(
            f'<div class="ga-row">'
            f'<a class="ga-letter" href="{href}" aria-label="Group {E(letter)}">{E(letter)}</a>'
            f'<div class="ga-teams">{"".join(chips)}</div>'
            f'<a class="ga-link" href="{href}" aria-label="Group {E(letter)} table">'
            f'<span class="arrow" aria-hidden="true">→</span></a></div>')
    return f"""
<section class="ko-archive" data-reveal aria-label="Group stage — final">
  <div class="sec-head"><h2>Group stage</h2><span class="muted">Final standings</span></div>
  <div class="ga-band">{"".join(rows)}</div>
</section>
"""


def _champion(ctx):
    """The tournament winner once the Final is decided, else None."""
    final_m = next((m for m in ctx.matches if m.get("round") == "Final"), None)
    if final_m is not None and data.has_result(final_m):
        return bracket.match_winner(final_m)
    return None
