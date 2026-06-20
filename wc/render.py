"""Render the static site (multi-page) from the live data + computed analyses.

Pages: groups home, per-group detail (with scenario viz), a team hub for every
nation, a searchable team directory, and a redesigned knockout bracket. The site
is team-agnostic — visitors pin any team(s) via a client-side watchlist.
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


# --------------------------------------------------------------------------
# Components
# --------------------------------------------------------------------------
def team_link(team, cls="team"):
    return (f'<a class="{cls}" data-team="{E(team)}" href="{util.page_for(team)}">'
            f'<span class="fl">{flag(team)}</span><span class="nm">{E(team)}</span></a>')


def star_icon(team):
    return (f'<button class="wl-ic" type="button" data-watch="{E(team)}" '
            f'aria-pressed="false" title="Watch {E(team)}"></button>')


def star(team, label="Watch"):
    return (f'<button class="wl" type="button" data-watch="{E(team)}" aria-pressed="false" '
            f'title="Pin {E(team)} to your watchlist">'
            f'<span class="wl-star">★</span><span class="wl-txt">{E(label)}</span></button>')


def slot_chip(res):
    if res["team"]:
        return team_link(res["team"])
    cands = sorted(res["candidates"])
    if 1 <= len(cands) <= 6:
        inner = " ".join(team_link(c, "cand") for c in cands)
        return (f'<span class="slot"><span class="slot-label">{E(res["label"])}</span>'
                f'<span class="slot-cands">{inner}</span></span>')
    extra = f" · {len(cands)} possible" if cands else ""
    return f'<span class="slot"><span class="slot-label">{E(res["label"])}{extra}</span></span>'


def bracket_slot(res):
    if res["team"]:
        return team_link(res["team"], "bteam")
    prov = res.get("provisional")
    code = res.get("slot", "")
    if prov:
        return f'{team_link(prov, "bteam prov")}<span class="bcode">{E(code)}</span>'
    return f'<span class="bslot">{E(res["label"])}</span>'


def status_badge(st):
    if st["won_group"]:
        return '<span class="badge win">Wins group</span>'
    if st["clinched_top2"]:
        return '<span class="badge q">Through</span>'
    if st["eliminated_top2"] and not st["can_top2"]:
        return '<span class="badge out">3rd hope</span>'
    return ""


def group_table(info, link_header=False, solo=False):
    """Render a group standings table.

    solo=True  -> standalone page (width-capped, shows the qualify-status column)
    link_header=True -> the group title links to its detail page (home grid)
    """
    letter = info["group"].split()[-1]
    rows = []
    for i, row in enumerate(info["table"], 1):
        t = row["team"]
        st = info["status"][t]
        cls = "qual" if i <= 2 else ("third" if i == 3 else "")
        status_cell = f'<td class="st">{status_badge(st)}</td>' if solo else ""
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
            f'<span class="arrow">→</span></h3></a>') if link_header else f'<h3>{E(info["group"])}</h3>'
    status_th = "<th></th>" if solo else ""
    return (
        f'<div class="card group-card{" solo" if solo else ""}">'
        f'<div class="group-head">{head}<span class="muted">{state}</span></div>'
        f'<table class="standings"><thead><tr>'
        f'<th></th><th></th><th class="tm">Team</th><th>P</th><th>W</th><th>D</th><th>L</th>'
        f'<th class="hide-s">GF</th><th class="hide-s">GA</th><th>GD</th><th>Pts</th>{status_th}'
        f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
    )


def dist_section(info, advance):
    """Scenario viz: within-group finish distribution + chance to advance.

    Bars show the share of remaining-result combinations finishing each position;
    the right-hand number is the Monte-Carlo chance of reaching the knockouts
    (top two OR one of the eight best third-placed teams).
    """
    dist = info["dist"]
    order = sorted(info["table"],
                   key=lambda r: (advance.get(r["team"], 0), r["Pts"], r["GD"]),
                   reverse=True)
    rows = []
    for r in order:
        t = r["team"]
        p = [x * 100 for x in dist[t]]
        adv = round(advance.get(t, 0) * 100)
        segs = []
        for k, val in enumerate(p, 1):
            if val < 0.5:
                continue
            lbl = f"{round(val)}%" if val >= 12 else ""
            segs.append(f'<span class="seg s{k}" style="width:{val:.3f}%" '
                        f'title="{round(val)}% finish {_ordinal(k)}">{lbl}</span>')
        advcls = "hi" if adv >= 75 else ("lo" if adv <= 25 else "")
        rows.append(
            f'<div class="dist-row" data-team="{E(t)}">'
            f'<div class="dist-team">{team_link(t)}</div>'
            f'<div class="dist-bar">{"".join(segs)}</div>'
            f'<div class="dist-adv {advcls}">{adv}%</div></div>'
        )
    note = ('Bars show each team\'s final-position split; the % is their chance of advancing. '
            + ("The group is decided — these reflect the remaining knockout picture."
               if info["complete"]
               else f'Based on {info["scenarios"]} possible group finishes plus a Monte-Carlo run of '
                    'the other groups for the best-third-place places.'))
    return (
        '<div class="card dist-card">'
        '<div class="dist-legend">'
        '<span><i class="sw s1"></i>1st</span><span><i class="sw s2"></i>2nd</span>'
        '<span><i class="sw s3"></i>3rd</span><span><i class="sw s4"></i>4th</span>'
        '<span class="dist-advh">advance to knockouts →</span></div>'
        f'<div class="dist">{"".join(rows)}</div>'
        f'<p class="muted dist-note">{note}</p></div>'
    )


def match_line(m, ctx):
    by_num = bracket.index_matches(ctx.matches)
    t1 = bracket.resolve_slot(m["team1"], ctx.analyses, by_num)
    t2 = bracket.resolve_slot(m["team2"], ctx.analyses, by_num)
    if data.has_result(m):
        g1, g2 = data.final_score(m)
        score = f'<span class="score">{g1}–{g2}</span>'
        pens = (m.get("score") or {}).get("p")
        if pens:
            score += f'<span class="pens">({pens[0]}–{pens[1]}p)</span>'
    else:
        score = f'<span class="vs">{E(m.get("time","") or "vs")}</span>'
    rd = m.get("round", "")
    rd_lbl = "" if str(rd).startswith("Matchday") else f'<span class="rd">{E(rd)}</span>'
    meta = f'{E(fmt_date(m.get("date","")))} · {E(venues.venue_str(m.get("ground","")))}'
    grp = m.get("group")
    grp_lbl = f'<span class="m-grp">{E(grp)}</span>' if grp else ""
    return (
        f'<div class="match">'
        f'<div class="m-meta">{grp_lbl}{rd_lbl}<span class="muted">{meta}</span></div>'
        f'<div class="m-row"><span class="m-side a">{slot_chip(t1)}</span>{score}'
        f'<span class="m-side b">{slot_chip(t2)}</span></div></div>'
    )


def match_list(ms, ctx, empty="None"):
    return "".join(match_line(m, ctx) for m in ms) or f'<div class="muted empty">{E(empty)}</div>'


def road_step(step, idx):
    return (
        f'<li class="step"><div class="step-rd"><span class="step-no">{idx}</span>{E(step["round"])}</div>'
        f'<div class="step-body"><div class="vs-lbl">vs</div>{slot_chip(step["opponent"])}'
        f'<div class="step-meta muted">{E(fmt_date(step.get("date","")))} · {E(venues.venue_str(step.get("ground","")))}</div>'
        f'</div></li>'
    )


def road_to_final(team, group_letter, ctx, slot, heading):
    path = bracket.project_path(team, ctx.matches, ctx.analyses, group_letter, slot)
    if not path:
        return ""
    steps = "".join(road_step(s, i + 1) for i, s in enumerate(path))
    return f'<div class="scenario"><h4>{heading}</h4><ol class="road">{steps}</ol></div>'


def team_card(ctx, team):
    proj = ctx.projections[team]
    pr, _ = util.accent(team)
    rec = proj["row"]
    return (
        f'<div class="tcard" data-team-card="{E(team)}" data-team="{E(team)}" style="--accent:{pr}">'
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


def shell(title, active, body, ctx):
    nav = "".join(
        f'<a class="{"on" if href == active else ""}" href="{href}">{E(label)}</a>'
        for href, label in NAV
    )
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
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{E(title)}</title>
<link rel="stylesheet" href="assets/style.css">
<script>window.WC_DEFAULT_WATCH={json.dumps(config.DEFAULT_WATCH)};</script>
</head>
<body>
<div class="bg-fx" aria-hidden="true"></div>
<header class="site-head">
  <div class="brand"><a href="index.html"><img class="ball" src="assets/ball.svg" alt="" width="22" height="22">World&nbsp;Cup&nbsp;<span class="grad">2026</span> <span class="brand-sub">tracker</span></a></div>
  <nav class="site-nav">{nav}</nav>
</header>
<main>
{body}
</main>
<footer class="site-foot">
  <div>Stage: <strong>{E(ctx.stage())}</strong> · {E(config.TOURNAMENT["hosts"])}</div>
  <div class="muted">Data: openfootball (public domain). Updated {E(updated) or "—"}. Projections follow the current standings; third-place bracket slots resolve via FIFA's allocation once the group stage ends.</div>
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
    thirds_rows = "".join(
        f'<tr class="{"qual" if r["qualifies"] else ""}" data-team="{E(r["team"])}">'
        f'<td class="pos">{r["seed"]}</td><td class="star">{star_icon(r["team"])}</td>'
        f'<td class="tm">{team_link(r["team"])}</td>'
        f'<td>{E(r["group"])}</td><td>{r["Pts"]}</td><td class="gd">{r["GD"]:+d}</td><td>{r["GF"]}</td>'
        f'<td>{"✓ in" if r["qualifies"] else "out"}</td></tr>'
        for r in ctx.thirds
    )
    n_played = sum(1 for m in ctx.matches if data.has_result(m))
    body = f"""
<section class="hero">
  <h1 class="grad-text">{E(config.TOURNAMENT["name"])}</h1>
  <div class="hero-chips">
    <span class="chip"><b>{E(ctx.stage())}</b></span>
    <span class="chip">{n_played}/{len(ctx.matches)} matches played</span>
  </div>
</section>

<section>
  <div class="sec-head"><h2>Your teams</h2><span class="muted">Pin any team with ★ — saved in your browser</span></div>
  <div id="your-teams" class="tcard-grid"></div>
  <div id="team-src" hidden>{src}</div>
</section>

<section>
  <div class="sec-head"><h2>Groups</h2><span class="muted">Tap a group title for fixtures &amp; scenarios</span></div>
  <div class="group-grid">{grid}</div>
</section>

<section>
  <div class="sec-head"><h2>Best third-placed teams</h2><span class="muted">provisional — eight advance</span></div>
  <div class="card"><table class="standings thirds">
  <thead><tr><th></th><th></th><th class="tm">Team</th><th>Group</th><th>Pts</th><th>GD</th><th>GF</th><th>R32</th></tr></thead>
  <tbody>{thirds_rows}</tbody></table></div>
</section>

<section class="cols">
  <div><h2>Latest results</h2><div class="match-list">{match_list(ctx.recent_results(5), ctx)}</div></div>
  <div><h2>Coming up</h2><div class="match-list">{match_list(ctx.upcoming(5), ctx)}</div></div>
</section>
"""
    return shell(config.TOURNAMENT["name"], "index.html", body, ctx)


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
  <div class="gb-tag">Group</div><div class="gb-letter">{E(letter)}</div>
  <div class="gb-main"><div class="gb-state">{E(state)}</div><div class="gb-teams">{chips}</div></div>
</section>

<section>
  <div class="sec-head"><h2>Standings</h2></div>
  {group_table(info, solo=True)}
</section>

<section>
  <div class="sec-head"><h2>Scenarios</h2><span class="muted">how the remaining games could finish the table</span></div>
  {dist_section(info, ctx.advance)}
</section>

<section><div class="sec-head"><h2>Upcoming games</h2></div>
  <div class="match-list">{match_list(upcoming, ctx, "Group complete")}</div></section>

<section><div class="sec-head"><h2>Completed games</h2></div>
  <div class="match-list">{match_list(completed, ctx, "None played yet")}</div></section>
"""
    return shell(f"Group {letter} — World Cup 2026", "", body, ctx)


def page_team(ctx, team):
    proj = ctx.projections[team]
    info = ctx.analyses[proj["group"]]
    pr, sec = util.accent(team)
    g = proj["group_letter"]
    ranks = set(proj["possible_ranks"])
    cur = proj["rank"]

    scenarios = []
    if 1 in ranks:
        scenarios.append(road_to_final(team, g, ctx, f"1{g}",
                         "Win the group (enter as 1%s)%s" % (g, " · current track" if cur == 1 else "")))
    if 2 in ranks:
        scenarios.append(road_to_final(team, g, ctx, f"2{g}",
                         "Finish runner-up (enter as 2%s)%s" % (g, " · current track" if cur == 2 else "")))
    third_html = _third_scenarios(ctx, proj) if 3 in ranks else ""

    group_results = [m for m in ctx.matches if m.get("group") == proj["group"]]
    gr_played = [m for m in group_results if data.has_result(m)]
    gr_upcoming = [m for m in group_results if not data.has_result(m)]

    body = f"""
<section class="team-hero" data-team="{E(team)}" style="--accent:{pr};--accent2:{sec}">
  <div class="th-flag">{flag(team)}</div>
  <div class="th-main">
    <h1>{E(team)}</h1>
    <p class="th-line"><a class="th-grp" href="group-{g.lower()}.html">{E(proj['group'])}</a> · {_ordinal(proj['rank'])} place · {proj['row']['Pts']} pts ({proj['row']['W']}W {proj['row']['D']}D {proj['row']['L']}L)</p>
    <p class="th-outlook">{_one_line_outlook(proj)}</p>
  </div>
  <div class="th-watch">{star(team, "Watch")}</div>
</section>

<section>
  <div class="sec-head"><h2>{E(proj['group'])} standings</h2></div>
  {group_table(info, solo=True)}
</section>

<section>
  <div class="sec-head"><h2>Potential futures — road to the final</h2></div>
  <p class="muted">Where the current table would send {E(team)} and who they could meet each round. Real names appear once results are in; otherwise the live candidates are shown.</p>
  <div class="scenarios">{third_html}{''.join(s for s in scenarios if s) or '<p class="muted">No knockout path yet — still alive in the group.</p>'}</div>
</section>

<section class="cols">
  <div><h2>Results</h2><div class="match-list">{match_list(gr_played, ctx, "None yet")}</div></div>
  <div><h2>Remaining group games</h2><div class="match-list">{match_list(gr_upcoming, ctx, "Group complete")}</div></div>
</section>
"""
    return shell(f"{team} — World Cup 2026", "", body, ctx)


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
<section><h1>All teams</h1>
<p class="muted">Tap a team to inspect its path to the final; ★ to follow it across the site.</p></section>
<section id="directory">
  <input id="team-search" class="team-search" type="search" placeholder="Search a team…" aria-label="Search teams">
  <div class="directory">{"".join(directory)}</div>
</section>
"""
    return shell("Teams — World Cup 2026", "teams.html", body, ctx)


def page_bracket(ctx):
    by_num = bracket.index_matches(ctx.matches)
    cols = []
    for rd, rows in ctx.bracket:
        if rd == "Match for third place":
            continue
        cells = []
        for r in rows:
            sides = []
            for key in ("team1", "team2"):
                res = r[key]
                g = ""
                if r["played"]:
                    g1, g2 = data.final_score({"score": r["score"]})
                    gv = g1 if key == "team1" else g2
                    winner = r["winner"]
                    wcls = " w" if winner and res["team"] == winner else ""
                    g = f'<span class="km-g{wcls}">{gv}</span>'
                sides.append(f'<div class="km-team">{bracket_slot(res)}{g}</div>')
            cells.append(
                f'<div class="km">'
                f'<div class="km-no">M{r["num"]} · {E(fmt_date_short(r.get("date","")))}</div>'
                f'{sides[0]}<div class="km-line"></div>{sides[1]}</div>'
            )
        head_lbl = (f'<img class="kr-trophy" src="assets/trophy.svg" alt="" width="18" height="18">{E(rd)}'
                    if rd == "Final" else E(rd))
        cols.append(f'<div class="kr-col"><div class="kr-head">{head_lbl}</div>{"".join(cells)}</div>')
    body = f"""
<section><h1 class="grad-text">Knockout bracket</h1>
<p class="muted">Round of 32 → Final. Pin teams with ★ and their matches glow across the bracket. Greyed slots resolve to real teams as results land (the small code shows the current table position).</p></section>
<section class="bracket-wrap"><div class="kbracket">{"".join(cols)}</div></section>
"""
    return shell("Bracket — World Cup 2026", "bracket.html", body, ctx)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _ordinal(n):
    return {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}.get(n, f"{n}th")


def _one_line_outlook(proj):
    st = proj["status"]
    g = proj["group"]
    if st["won_group"]:
        return f'Through to the Round of 32 as <strong>{E(g)} winners</strong>.'
    if st["clinched_top2"]:
        return f'<strong>Qualified</strong> for the Round of 32 from {E(g)}.'
    if proj["rank"] <= 2 and not proj["group_complete"]:
        return f'Currently {_ordinal(proj["rank"])} in {E(g)} — in the top two.'
    if proj["rank"] == 3:
        return f'3rd in {E(g)} — chasing a best-third-place spot.'
    return f'{_ordinal(proj["rank"])} in {E(g)} — work to do.'


def _third_scenarios(ctx, proj):
    by_num = bracket.index_matches(ctx.matches)
    rows = []
    for tgt in proj["third_targets"]:
        m = by_num[tgt["num"]]
        opp_slot = m["team2"] if str(m["team1"]).startswith("3") else m["team1"]
        opp = bracket.resolve_slot(opp_slot, ctx.analyses, by_num)
        rows.append(
            f'<li class="step"><div class="step-rd"><span class="step-no">R32</span>M{m["num"]}</div>'
            f'<div class="step-body"><div class="vs-lbl">vs</div>{slot_chip(opp)}'
            f'<div class="step-meta muted">{E(fmt_date(m.get("date","")))} · {E(venues.venue_str(m.get("ground","")))}</div></div></li>'
        )
    if not rows:
        return ""
    return ('<div class="scenario third"><h4>Sneak through as a best third place</h4>'
            '<p class="muted">A third-placed finish could land in any of these Round-of-32 slots '
            '(FIFA fixes the exact one once all groups finish):</p>'
            f'<ol class="road">{"".join(rows)}</ol></div>')


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
<g fill="#fbbf24" stroke="#d97706" stroke-width="1.3" stroke-linejoin="round">
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


APP_JS = r"""
(function(){
  var KEY='wc26.watch';
  var DEFAULT=Array.isArray(window.WC_DEFAULT_WATCH)?window.WC_DEFAULT_WATCH:[];
  function get(){try{var v=JSON.parse(localStorage.getItem(KEY));if(Array.isArray(v))return v;}catch(e){}return DEFAULT.slice();}
  function save(a){try{localStorage.setItem(KEY,JSON.stringify(a));}catch(e){}}
  function toggle(t){var a=get();var i=a.indexOf(t);if(i>=0)a.splice(i,1);else a.push(t);save(a);apply();}
  function apply(){
    var w=get();
    var host=document.getElementById('your-teams');
    if(host){
      host.innerHTML='';
      if(!w.length){host.innerHTML='<p class="muted empty">No teams pinned yet — tap ★ on any team to follow it here.</p>';}
      else{w.forEach(function(t){
        var src=document.querySelector('#team-src [data-team-card="'+t.replace(/"/g,'\\"')+'"]')
              ||document.querySelector('[data-team-card="'+t.replace(/"/g,'\\"')+'"]');
        if(src)host.appendChild(src.cloneNode(true));
      });}
    }
    document.querySelectorAll('[data-team]').forEach(function(el){
      el.classList.toggle('watched',w.indexOf(el.getAttribute('data-team'))>=0);
    });
    document.querySelectorAll('.bm,.match,.km,.dist-row').forEach(function(el){
      el.classList.toggle('has-watched',!!el.querySelector('.watched'));
    });
    document.querySelectorAll('[data-watch]').forEach(function(btn){
      var on=w.indexOf(btn.getAttribute('data-watch'))>=0;
      btn.classList.toggle('on',on);btn.setAttribute('aria-pressed',on);
      var lab=btn.querySelector('.wl-txt');if(lab)lab.textContent=on?'Watching':'Watch';
    });
  }
  document.addEventListener('click',function(e){
    var b=e.target.closest&&e.target.closest('[data-watch]');
    if(b){e.preventDefault();toggle(b.getAttribute('data-watch'));}
  });
  document.addEventListener('input',function(e){
    if(e.target.id!=='team-search')return;
    var q=e.target.value.trim().toLowerCase();
    document.querySelectorAll('#directory .tcard').forEach(function(c){
      var n=(c.getAttribute('data-team-card')||'').toLowerCase();
      c.style.display=(!q||n.indexOf(q)>=0)?'':'none';
    });
    document.querySelectorAll('.dir-group').forEach(function(g){
      g.style.display=g.querySelector('.tcard:not([style*="display: none"])')?'':'none';
    });
  });
  document.addEventListener('DOMContentLoaded',apply);
})();
"""

STYLE = r"""
:root{
  --bg:#091210;--panel:rgba(17,28,26,.74);--panel2:#122220;--line:rgba(255,255,255,.10);
  --text:#eaf3f0;--muted:#8ba79f;--accent:#2dd4bf;
  --i1:#34d399;--i2:#2dd4bf;--i3:#22d3ee;--cyan:#22d3ee;
  --green:#34d399;--amber:#fbbf24;--orange:#fb923c;--slate:#64748b;
  --grad:linear-gradient(120deg,#34d399,#2dd4bf,#22d3ee);
  --glow:rgba(45,212,191,.55);
  --maxw:1200px;--r:16px;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--text);overflow-x:hidden;
  font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
a{color:inherit;text-decoration:none}
h1,h2,h3,h4{line-height:1.18;margin:0 0 .5em;letter-spacing:-.01em}
h1{font-size:2.1rem}h2{font-size:1.4rem}
.muted{color:var(--muted);font-size:.9em}
main{max-width:var(--maxw);margin:0 auto;padding:18px 18px 80px;position:relative;z-index:1}

/* animated background */
.bg-fx{position:fixed;inset:0;z-index:0;pointer-events:none;
  background:
    radial-gradient(38vw 38vw at 12% -5%,rgba(52,211,153,.26),transparent 60%),
    radial-gradient(34vw 34vw at 95% 8%,rgba(34,211,238,.20),transparent 60%),
    radial-gradient(40vw 40vw at 70% 100%,rgba(45,212,191,.18),transparent 60%);
  filter:saturate(1.1);animation:drift 22s ease-in-out infinite alternate}
@keyframes drift{from{transform:translate3d(0,0,0) scale(1)}to{transform:translate3d(0,-3%,0) scale(1.08)}}

/* section spacing + reveal */
section{margin:46px 0;animation:fadeUp .55s both}
section:nth-of-type(2){animation-delay:.05s}
section:nth-of-type(3){animation-delay:.1s}
section:nth-of-type(4){animation-delay:.15s}
@keyframes fadeUp{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
.sec-head{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:14px}
.sec-head h2,section>h2{position:relative;padding-left:14px}
.sec-head h2::before,section>h2::before{content:"";position:absolute;left:0;top:.1em;bottom:.1em;width:5px;border-radius:3px;background:var(--grad)}
.sec-head h2{margin:0}

/* header */
.site-head{position:sticky;top:0;z-index:20;display:flex;align-items:center;gap:18px;
  justify-content:space-between;padding:12px 20px;
  background:rgba(10,12,18,.72);backdrop-filter:blur(14px);border-bottom:1px solid var(--line)}
.brand a{font-weight:800;font-size:1.06rem;letter-spacing:.2px}
.brand .grad{background:var(--grad);-webkit-background-clip:text;background-clip:text;color:transparent}
.brand-sub{color:var(--muted);font-weight:600}
.site-nav{display:flex;gap:6px;flex-wrap:wrap}
.site-nav a{padding:8px 14px;border-radius:11px;color:var(--muted);font-weight:700;font-size:.92rem;transition:.15s}
.site-nav a:hover{color:var(--text);background:rgba(255,255,255,.06)}
.site-nav a.on{color:#fff;background:var(--grad);box-shadow:0 6px 20px -8px var(--i2)}

/* hero */
.hero{text-align:center;padding:36px 0 4px}
.hero h1{font-size:3rem;margin-bottom:.1em}
.grad-text{background:linear-gradient(120deg,var(--i1),var(--i2),var(--i3),var(--cyan));
  background-size:240% auto;-webkit-background-clip:text;background-clip:text;color:transparent;animation:sheen 8s linear infinite}
@keyframes sheen{to{background-position:240% center}}
.hero-sub{color:var(--muted)}
.hero-chips{display:flex;gap:10px;justify-content:center;flex-wrap:wrap;margin-top:16px}
.chip{padding:7px 14px;border-radius:999px;background:var(--panel);border:1px solid var(--line);
  backdrop-filter:blur(8px);font-size:.9rem}
.chip b{background:var(--grad);-webkit-background-clip:text;background-clip:text;color:transparent}

/* cards (glass) */
.card{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);
  backdrop-filter:blur(10px);box-shadow:0 12px 40px -24px #000}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:24px}
.match-list{display:flex;flex-direction:column;gap:9px}

/* legend */
.legend{display:flex;gap:18px;flex-wrap:wrap;margin:0 0 14px;color:var(--muted);font-size:.86rem}
.legend .lg{display:inline-flex;align-items:center;gap:7px}
.dot{width:11px;height:11px;border-radius:3px;display:inline-block}
.dot.green{background:var(--green)}.dot.amber{background:var(--amber)}
.star-mini{color:var(--amber);font-style:normal}

/* match line */
.match{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:9px 13px;transition:.16s}
.match:hover{border-color:var(--accent);transform:translateY(-2px);box-shadow:0 12px 30px -18px var(--glow)}
.match.has-watched{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent),0 10px 28px -16px var(--glow)}
.m-meta{display:flex;gap:8px;align-items:center;font-size:.76rem;color:var(--muted);margin-bottom:5px}
.m-grp{font-weight:700;color:var(--text)}
.m-row{display:flex;align-items:center;justify-content:center;gap:14px}
.m-side{display:flex;align-items:center;flex:0 1 240px;min-width:0}
.m-side.a{justify-content:flex-end;text-align:right}
.m-side.b{justify-content:flex-start}
.m-side .nm{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.score{font-weight:800;font-size:1.08rem;padding:0 6px;white-space:nowrap}
.pens{font-size:.7rem;color:var(--muted);margin-left:3px}
.vs{color:var(--muted);font-size:.8rem;white-space:nowrap}
.rd{background:rgba(255,255,255,.07);border:1px solid var(--line);border-radius:6px;padding:1px 7px;font-size:.7rem}

/* team chips/links */
.team,.cand,.bteam{display:inline-flex;align-items:center;gap:6px;font-weight:650;border-radius:7px;padding:1px 4px;transition:.12s}
.team .fl,.cand .fl,.bteam .fl{font-size:1.08em}
.team:hover,.cand:hover,.bteam:hover{color:#fff;background:rgba(255,255,255,.07)}
.team.watched,.cand.watched,.bteam.watched{background:rgba(45,212,191,.2);box-shadow:inset 0 0 0 1px var(--accent);font-weight:800}
.cand{font-size:.76rem;background:var(--panel2);border:1px solid var(--line);padding:2px 6px}
.slot{display:inline-flex;flex-direction:column;gap:3px}
.slot-label{color:var(--muted);font-weight:600;font-size:.88em}
.slot-cands{display:flex;flex-wrap:wrap;gap:4px}

/* tables */
.group-card{overflow:hidden;transition:.18s;animation:fadeUp .5s both}
.group-card:hover{transform:translateY(-3px);border-color:var(--accent);box-shadow:0 16px 40px -22px var(--glow)}
.group-card.solo{overflow-x:auto;width:fit-content;max-width:100%;margin:0 auto}
.group-card.solo .standings{width:100%}
.group-card.solo .standings .tm{padding-right:26px}
.group-head{display:flex;justify-content:space-between;align-items:center;padding:11px 15px;border-bottom:1px solid var(--line)}
.group-head h3{margin:0;font-size:1.05rem}
.group-link{display:inline-flex}.group-link .arrow{color:var(--accent);transition:.15s;display:inline-block}
.group-link:hover{color:#fff}.group-link:hover .arrow{transform:translateX(4px)}
table.standings{width:100%;border-collapse:collapse;font-size:.86rem}
.standings th,.standings td{padding:7px 5px;text-align:center}
.standings th{color:var(--muted);font-weight:600;font-size:.7rem;text-transform:uppercase;letter-spacing:.4px}
.standings .tm{text-align:left;width:100%}
.group-card.solo .standings .tm{width:auto}
.standings td.pos{color:var(--muted);width:20px;font-weight:700}
.standings td.star{width:22px;padding:0}
.standings td.pts{font-weight:800}
.standings .gd{color:var(--muted)}
.standings tbody tr{border-top:1px solid var(--line);transition:.12s}
.standings tr.qual td.pos{box-shadow:inset 3px 0 0 var(--green)}
.standings tr.third td.pos{box-shadow:inset 3px 0 0 var(--amber)}
.standings tr.watched{background:rgba(45,212,191,.12)}
.badge{font-size:.66rem;font-weight:800;border-radius:20px;padding:2px 8px;white-space:nowrap}
.badge.win{background:rgba(52,211,153,.18);color:#6ee7b7}
.badge.q{background:rgba(52,211,153,.12);color:#a7f3d0}
.badge.out{background:rgba(251,191,36,.16);color:var(--amber)}
.group-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:18px}
.thirds td{padding:8px 6px}

/* star buttons */
.wl-ic{width:24px;height:24px;border:0;background:none;cursor:pointer;color:var(--muted);
  font-size:1.05rem;line-height:1;padding:0;transition:.12s}
.wl-ic::before{content:"\2606"}
.wl-ic:hover{color:var(--amber);transform:scale(1.18)}
.wl-ic.on{color:var(--amber)}.wl-ic.on::before{content:"\2605"}
.wl{display:inline-flex;align-items:center;gap:6px;cursor:pointer;border-radius:999px;
  border:1px solid var(--line);background:var(--panel2);color:var(--muted);font-weight:800;font-size:.84rem;padding:7px 15px;transition:.15s}
.wl:hover{color:var(--text);border-color:var(--accent)}
.wl.on{background:linear-gradient(120deg,var(--amber),var(--orange));border-color:transparent;color:#1a1305}
.wl .wl-star{color:inherit}

/* directory + your teams */
.tcard-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(232px,1fr));gap:11px}
.tcard{display:flex;align-items:center;gap:8px;background:var(--panel);border:1px solid var(--line);
  border-left:4px solid var(--accent);border-radius:12px;padding:9px 11px;transition:.15s}
.tcard:hover{transform:translateY(-3px);border-color:var(--accent);box-shadow:0 14px 34px -20px var(--glow)}
.tcard.watched{box-shadow:0 0 0 1px var(--accent),0 10px 30px -18px var(--i2)}
.tcard-main{display:flex;align-items:center;gap:10px;flex:1;min-width:0}
.tcard-flag{font-size:1.5rem}
.tcard-body{display:flex;flex-direction:column;min-width:0}
.tcard-name{font-weight:800;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tcard-meta{font-size:.76rem}
.directory{display:flex;flex-direction:column;gap:20px}
.dir-group .dir-head{font-weight:800;margin-bottom:9px}
.dir-group .dir-head a:hover{color:var(--accent)}
.team-search{width:100%;max-width:380px;margin-bottom:16px;padding:11px 14px;border-radius:12px;
  border:1px solid var(--line);background:var(--panel);color:var(--text);font-size:.95rem;backdrop-filter:blur(8px)}
.empty{padding:16px;border:1px solid var(--line);border-radius:12px}

/* scenario distribution */
.dist-card{padding:16px 18px}
.dist-legend{display:flex;gap:16px;flex-wrap:wrap;color:var(--muted);font-size:.78rem;margin-bottom:12px;align-items:center}
.dist-legend span{display:inline-flex;align-items:center;gap:6px}
.sw{width:13px;height:13px;border-radius:4px;display:inline-block}
.s1{background:var(--amber)}.s2{background:var(--green)}.s3{background:var(--orange)}.s4{background:var(--slate)}
.dist-advh{margin-left:auto;font-weight:700;color:var(--text)}
.dist{display:flex;flex-direction:column;gap:10px}
.dist-row{display:grid;grid-template-columns:160px 1fr 46px;align-items:center;gap:12px}
.dist-row.has-watched .dist-team{font-weight:800}
.dist-team{min-width:0;overflow:hidden}
.dist-bar{display:flex;height:22px;border-radius:7px;overflow:hidden;background:var(--panel2);box-shadow:inset 0 0 0 1px var(--line)}
.dist-bar .seg{display:flex;align-items:center;justify-content:center;font-size:.66rem;font-weight:800;color:#10131c;
  min-width:0;transition:width .5s ease}
.dist-bar .seg.s4{color:#dde3ee}
.dist-adv{text-align:right;font-weight:800}
.dist-adv.hi{color:var(--green)}
.dist-adv.lo{color:var(--muted)}
.dist-note{margin:12px 2px 0}

/* team hero */
.team-hero{display:flex;align-items:center;gap:22px;border-radius:22px;padding:26px 28px;color:#fff;flex-wrap:wrap;
  background:linear-gradient(120deg,var(--accent),var(--accent2));position:relative;overflow:hidden;
  box-shadow:0 24px 60px -30px var(--accent)}
.team-hero::after{content:"";position:absolute;inset:0;background:radial-gradient(60% 120% at 100% 0,rgba(255,255,255,.25),transparent 60%)}
.th-flag{font-size:3.8rem;position:relative}
.th-main{flex:1;min-width:200px;position:relative}
.team-hero h1{margin:0;font-size:2.1rem;color:#fff}
.th-line{margin:5px 0;opacity:.96}.th-grp{text-decoration:underline;text-underline-offset:3px}
.th-outlook{margin:6px 0 0;font-weight:700}
.th-watch{position:relative}
.th-watch .wl{background:rgba(255,255,255,.18);border-color:rgba(255,255,255,.55);color:#fff}
.th-watch .wl.on{background:#fff;color:#16140b;border-color:#fff}

/* group banner */
.group-banner{display:flex;align-items:center;gap:18px;border-radius:22px;padding:22px 26px;
  background:var(--grad);color:#fff;box-shadow:0 24px 60px -34px var(--i2)}
.gb-tag{font-weight:700;text-transform:uppercase;letter-spacing:2px;opacity:.85;font-size:.8rem;writing-mode:vertical-rl;transform:rotate(180deg)}
.gb-letter{font-size:3.6rem;font-weight:900;line-height:1}
.gb-main{flex:1}.gb-state{font-weight:700;opacity:.95;margin-bottom:8px}
.gb-teams{display:flex;flex-wrap:wrap;gap:8px}
.gb-teams .team{background:rgba(255,255,255,.16);color:#fff}

/* road / scenarios */
.scenarios{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.scenario{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px 18px}
.scenario.third{grid-column:1/-1}
.scenario h4{margin:0 0 12px}
.road{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:9px}
.step{display:flex;gap:12px;align-items:flex-start}
.step-rd{display:flex;align-items:center;gap:8px;min-width:140px;font-weight:700;font-size:.84rem;color:var(--muted)}
.step-no{display:inline-grid;place-items:center;min-width:34px;height:24px;padding:0 6px;border-radius:7px;
  background:var(--grad);color:#fff;font-size:.7rem;font-weight:900}
.step-body{flex:1;border-left:2px solid var(--line);padding:0 0 6px 13px}
.vs-lbl{font-size:.68rem;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}

/* redesigned bracket */
.bracket-wrap{overflow-x:auto;padding-bottom:8px}
.kbracket{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;min-width:920px}
.kr-col{min-width:0}
.kr-head{font-size:.8rem;font-weight:800;text-transform:uppercase;letter-spacing:.6px;color:var(--muted);
  margin-bottom:10px;padding-bottom:6px;border-bottom:2px solid;border-image:var(--grad) 1}
.km{background:var(--panel);border:1px solid var(--line);border-radius:11px;padding:8px 10px;margin-bottom:10px;transition:.15s}
.km:hover{border-color:var(--accent);transform:translateY(-2px);box-shadow:0 12px 28px -18px var(--glow)}
.km.has-watched{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent),0 10px 28px -16px var(--glow)}
.km-no{font-size:.66rem;color:var(--muted);margin-bottom:5px}
.km-line{height:1px;background:var(--line);margin:5px 0}
.km-team{display:flex;align-items:center;gap:5px;min-width:0;font-size:.85rem}
.km-team .bteam{min-width:0;font-weight:700}
.km-team .bteam .nm{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.km-team .bteam.prov{color:var(--muted);font-weight:600}
.bcode{font-size:.62rem;color:var(--muted);background:rgba(255,255,255,.06);border:1px solid var(--line);
  border-radius:5px;padding:0 5px;margin-left:2px}
.bslot{color:var(--muted);font-size:.8rem;font-weight:600}
.km-g{margin-left:auto;font-weight:800;color:var(--muted);min-width:16px;text-align:right}
.km-g.w{color:var(--text)}

/* graphics (original SVGs, no trademarks) */
.brand a{display:inline-flex;align-items:center;gap:9px}
.brand .ball{transition:transform .6s cubic-bezier(.2,.8,.2,1)}
.brand a:hover .ball{transform:rotate(360deg)}
.hero{position:relative}
.hero::before{content:"";position:absolute;left:50%;top:54%;transform:translate(-50%,-50%);
  width:min(340px,64%);aspect-ratio:320/200;background:url(pitch.svg) center/contain no-repeat;
  opacity:.06;z-index:-1;pointer-events:none}
.team-hero::before{content:"";position:absolute;right:14px;bottom:-34px;width:150px;height:150px;
  background:url(ball.svg) center/contain no-repeat;opacity:.16;transform:rotate(-12deg);z-index:0}
.group-banner{position:relative;overflow:hidden}
.group-banner::before{content:"";position:absolute;right:-22px;top:-30px;width:172px;height:172px;
  background:url(ball.svg) center/contain no-repeat;opacity:.14;transform:rotate(14deg)}
.kr-trophy{vertical-align:-3px;margin-right:5px;filter:drop-shadow(0 2px 6px rgba(251,191,36,.5))}

/* footer */
.site-foot{max-width:var(--maxw);margin:0 auto;padding:26px 18px 60px;border-top:1px solid var(--line);
  display:flex;flex-direction:column;gap:6px;position:relative;z-index:1}

@media(max-width:760px){
  .cols,.scenarios{grid-template-columns:1fr}
  .group-grid{grid-template-columns:1fr}
  .team-hero,.group-banner{flex-direction:column;text-align:center}
  .standings .hide-s{display:none}
  .dist-row{grid-template-columns:120px 1fr 40px}
  h1{font-size:1.7rem}.hero h1{font-size:2.1rem}
}
@media(prefers-reduced-motion:reduce){
  *{animation:none!important;transition:none!important;scroll-behavior:auto}
  .bg-fx{animation:none}
}
"""
