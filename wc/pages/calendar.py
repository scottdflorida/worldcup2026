"""Full tournament calendar page: every matchday laid out Sun→Sat in
Pacific time."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .. import bracket, data
from ..components import _round_short, side_result, team_link, wl_badge
from ..shell import shell
from ..times import E, PT_OFFSET_HOURS, _pt_datetime, _pt_parts, _utc_iso


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
