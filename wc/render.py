"""Render the static site (multi-page) from the live data + computed analyses.

The site is team-agnostic: every nation gets a hub page, and visitors pin
whichever teams they want via a client-side watchlist (assets/app.js).
"""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone

from . import bracket, config, data, standings, util
from .flags import flag

E = html.escape


# --------------------------------------------------------------------------
# Shared context computed once per build
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
        self.last_updated = data.last_updated()

    def sorted_matches(self):
        return sorted(self.matches, key=lambda m: (m.get("date", ""), m.get("time", "")))

    def recent_results(self, n=6):
        played = [m for m in self.sorted_matches() if data.has_result(m)]
        return played[-n:][::-1]

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
# Small components
# --------------------------------------------------------------------------
def team_name(team):
    return (f'<span class="team" data-team="{E(team)}">'
            f'<span class="fl">{flag(team)}</span>{E(team)}</span>')


def star(team, label="Watch"):
    return (f'<button class="wl" type="button" data-watch="{E(team)}" aria-pressed="false" '
            f'title="Pin {E(team)} to your watchlist">'
            f'<span class="wl-star">★</span><span class="wl-txt">{E(label)}</span></button>')


def slot_chip(res):
    if res["team"]:
        return team_name(res["team"])
    cands = sorted(res["candidates"])
    if 1 <= len(cands) <= 6:
        inner = " ".join(
            f'<span class="cand" data-team="{E(c)}">{flag(c)} {E(c)}</span>' for c in cands)
        return (f'<span class="slot"><span class="slot-label">{E(res["label"])}</span>'
                f'<span class="slot-cands">{inner}</span></span>')
    extra = f" · {len(cands)} possible" if cands else ""
    return f'<span class="slot"><span class="slot-label">{E(res["label"])}{extra}</span></span>'


def status_badge(st):
    if st["won_group"]:
        return '<span class="badge win">Wins group</span>'
    if st["clinched_top2"]:
        return '<span class="badge q">Through</span>'
    if st["eliminated_top2"] and not st["can_top2"]:
        return '<span class="badge out">3rd-place hope</span>'
    return ""


def group_table(info):
    rows = []
    for i, row in enumerate(info["table"], 1):
        t = row["team"]
        st = info["status"][t]
        cls = "qual" if i <= 2 else ("third" if i == 3 else "")
        rows.append(
            f'<tr class="{cls}" data-team="{E(t)}">'
            f'<td class="pos">{i}</td>'
            f'<td class="tm">{team_name(t)}</td>'
            f'<td>{row["P"]}</td><td>{row["W"]}</td><td>{row["D"]}</td><td>{row["L"]}</td>'
            f'<td>{row["GF"]}</td><td>{row["GA"]}</td><td class="gd">{row["GD"]:+d}</td>'
            f'<td class="pts">{row["Pts"]}</td>'
            f'<td class="st">{status_badge(st)}</td></tr>'
        )
    state = "Final" if info["complete"] else f'{info["remaining"]} to play'
    return (
        f'<div class="card group-card">'
        f'<div class="group-head"><h3>{E(info["group"])}</h3><span class="muted">{state}</span></div>'
        f'<table class="standings"><thead><tr>'
        f'<th></th><th class="tm">Team</th><th>P</th><th>W</th><th>D</th><th>L</th>'
        f'<th>GF</th><th>GA</th><th>GD</th><th>Pts</th><th></th>'
        f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
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
            score += f'<span class="pens">({pens[0]}–{pens[1]} pen)</span>'
    else:
        score = f'<span class="vs">{E(m.get("time","") or "vs")}</span>'
    rd = m.get("round", "")
    rd_lbl = "" if str(rd).startswith("Matchday") else f'<span class="rd">{E(rd)}</span>'
    meta = f'{E(m.get("date",""))} · {E(m.get("ground",""))}'
    return (
        f'<div class="match">'
        f'<div class="m-meta">{E(m.get("group") or "")} {rd_lbl}<span class="muted">{meta}</span></div>'
        f'<div class="m-row"><span class="m-side a">{slot_chip(t1)}</span>{score}'
        f'<span class="m-side b">{slot_chip(t2)}</span></div></div>'
    )


def road_step(step, idx):
    return (
        f'<li class="step"><div class="step-rd"><span class="step-no">{idx}</span>{E(step["round"])}</div>'
        f'<div class="step-body"><div class="vs-lbl">vs</div>{slot_chip(step["opponent"])}'
        f'<div class="step-meta muted">M{step["num"]} · {E(step.get("date",""))} · {E(step.get("ground",""))}</div>'
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
        f'</a>{star(team)}</div>'
    )


# --------------------------------------------------------------------------
# Page shell
# --------------------------------------------------------------------------
NAV = [
    ("index.html", "Home"),
    ("index.html#directory", "Teams"),
    ("groups.html", "Groups"),
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
    default_watch = json.dumps(config.DEFAULT_WATCH)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{E(title)}</title>
<link rel="stylesheet" href="assets/style.css">
<script>window.WC_DEFAULT_WATCH={default_watch};</script>
</head>
<body>
<header class="site-head">
  <div class="brand"><a href="index.html">World Cup 2026 <span class="brand-sub">tracker</span></a></div>
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
    results = "".join(match_line(m, ctx) for m in ctx.recent_results(6))
    upcoming = "".join(match_line(m, ctx) for m in ctx.upcoming(6))

    directory = []
    for g in sorted(ctx.analyses):
        info = ctx.analyses[g]
        cards = "".join(team_card(ctx, row["team"]) for row in info["table"])
        directory.append(
            f'<div class="dir-group"><div class="dir-head">{E(g)} '
            f'<span class="muted">{"Final" if info["complete"] else str(info["remaining"]) + " to play"}</span></div>'
            f'<div class="tcard-grid">{cards}</div></div>'
        )

    body = f"""
<section class="hero">
  <h1>{E(config.TOURNAMENT["name"])}</h1>
  <p class="hero-sub">{E(config.TOURNAMENT["hosts"])} · {E(config.TOURNAMENT["start"])} – {E(config.TOURNAMENT["final_date"])} · {config.TOURNAMENT["teams"]} teams</p>
  <p class="hero-stage">Now: <strong>{E(ctx.stage())}</strong></p>
</section>

<section>
  <div class="sec-head"><h2>Your teams</h2><span class="muted">Pin any team with ★ — saved in your browser</span></div>
  <div id="your-teams" class="tcard-grid"></div>
</section>

<section class="cols">
  <div><h2>Latest results</h2><div class="match-list">{results}</div></div>
  <div><h2>Coming up</h2><div class="match-list">{upcoming}</div></div>
</section>

<section id="directory">
  <div class="sec-head"><h2>All teams</h2><span class="muted">Tap a team to inspect its path; ★ to follow it</span></div>
  <input id="team-search" class="team-search" type="search" placeholder="Search a team…" aria-label="Search teams">
  <div class="directory">{"".join(directory)}</div>
</section>
"""
    return shell(config.TOURNAMENT["name"], "index.html", body, ctx)


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
    gr_played = "".join(match_line(m, ctx) for m in group_results if data.has_result(m))
    gr_upcoming = "".join(match_line(m, ctx) for m in group_results if not data.has_result(m))

    body = f"""
<section class="team-hero" data-team="{E(team)}" style="--accent:{pr};--accent2:{sec}">
  <div class="th-flag">{flag(team)}</div>
  <div class="th-main">
    <h1>{E(team)}</h1>
    <p class="th-line">{E(proj['group'])} · {_ordinal(proj['rank'])} place · {proj['row']['Pts']} pts ({proj['row']['W']}W {proj['row']['D']}D {proj['row']['L']}L)</p>
    <p class="th-outlook">{_one_line_outlook(proj)}</p>
  </div>
  <div class="th-watch">{star(team, "Watch")}</div>
</section>

<section><h2>{E(proj['group'])} standings</h2>{group_table(info)}</section>

<section><h2>Potential futures — road to the final</h2>
  <p class="muted">Where the current table would send {E(team)} and who they could meet at each round. Real names appear once results are in; otherwise the live candidates are shown.</p>
  {third_html}
  <div class="scenarios">{''.join(s for s in scenarios if s) or '<p class="muted">No knockout path yet — still alive in the group.</p>'}</div>
</section>

<section class="cols">
  <div><h2>Results</h2><div class="match-list">{gr_played or '<div class="muted">None yet</div>'}</div></div>
  <div><h2>Remaining group games</h2><div class="match-list">{gr_upcoming or '<div class="muted">Group complete</div>'}</div></div>
</section>
"""
    return shell(f"{team} — World Cup 2026", "", body, ctx)


def page_groups(ctx):
    cards = "".join(group_table(ctx.analyses[g]) for g in sorted(ctx.analyses))
    thirds_rows = "".join(
        f'<tr class="{"qual" if r["qualifies"] else ""}" data-team="{E(r["team"])}">'
        f'<td class="pos">{r["seed"]}</td><td class="tm">{team_name(r["team"])}</td>'
        f'<td>{E(r["group"])}</td><td>{r["Pts"]}</td><td class="gd">{r["GD"]:+d}</td><td>{r["GF"]}</td>'
        f'<td>{"✓ in" if r["qualifies"] else "out"}</td></tr>'
        for r in ctx.thirds
    )
    body = f"""
<section><h1>Groups & standings</h1>
<p class="muted">Top two of each group advance, plus the eight best third-placed teams. Pin teams with ★ to highlight them here.</p></section>
<section class="group-grid">{cards}</section>
<section><h2>Best third-placed teams <span class="muted">(provisional)</span></h2>
<div class="card"><table class="standings thirds">
<thead><tr><th></th><th class="tm">Team</th><th>Group</th><th>Pts</th><th>GD</th><th>GF</th><th>R32</th></tr></thead>
<tbody>{thirds_rows}</tbody></table></div></section>
"""
    return shell("Groups — World Cup 2026", "groups.html", body, ctx)


def page_bracket(ctx):
    cols = []
    for rd, rows in ctx.bracket:
        if rd == "Match for third place":
            continue
        cells = []
        for r in rows:
            if r["played"]:
                g1, g2 = data.final_score({"score": r["score"]})
                sc = f'<span class="bm-score">{g1}–{g2}</span>'
            else:
                sc = '<span class="bm-score muted">—</span>'
            cells.append(
                f'<div class="bm"><div class="bm-no">M{r["num"]} · {E(r.get("date",""))}</div>'
                f'<div class="bm-side">{slot_chip(r["team1"])}</div>'
                f'<div class="bm-mid">{sc}</div>'
                f'<div class="bm-side">{slot_chip(r["team2"])}</div></div>'
            )
        cols.append(f'<div class="br-col"><h3>{E(rd)}</h3>{"".join(cells)}</div>')
    body = f"""
<section><h1>Knockout bracket</h1>
<p class="muted">Round of 32 through the final. Pin teams with ★ and their matches light up across the bracket. Slots resolve to real teams as results come in.</p></section>
<section class="bracket-scroll"><div class="bracket">{"".join(cols)}</div></section>
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
            f'<div class="step-meta muted">{E(m.get("date",""))} · {E(m.get("ground",""))}</div></div></li>'
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
        "groups.html": page_groups(ctx),
        "bracket.html": page_bracket(ctx),
        "assets/style.css": STYLE,
        "assets/app.js": APP_JS,
    }
    for team in ctx.teams:
        files[util.page_for(team)] = page_team(ctx, team)
    return files


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
      if(!w.length){host.innerHTML='<p class="muted empty">No teams pinned yet — tap ★ on any team below to follow it here.</p>';}
      else{w.forEach(function(t){
        var src=document.querySelector('[data-team-card="'+t.replace(/"/g,'\\"')+'"]');
        if(src)host.appendChild(src.cloneNode(true));
      });}
    }
    document.querySelectorAll('[data-team]').forEach(function(el){
      el.classList.toggle('watched',w.indexOf(el.getAttribute('data-team'))>=0);
    });
    document.querySelectorAll('.bm,.match').forEach(function(el){
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
      var any=g.querySelector('.tcard:not([style*="display: none"])');
      g.style.display=any?'':'none';
    });
  });
  document.addEventListener('DOMContentLoaded',apply);
})();
"""


STYLE = r"""
:root{
  --bg:#0e1116;--panel:#161b22;--panel2:#1c232d;--line:#2b333d;
  --text:#e7edf3;--muted:#8b97a5;--accent:#3b82f6;
  --green:#16a34a;--amber:#d97706;--gold:#fbbf24;--maxw:1180px;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--text);
  font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
a{color:inherit;text-decoration:none}
h1,h2,h3,h4{line-height:1.2;margin:0 0 .5em}
h1{font-size:2rem}h2{font-size:1.35rem}
.muted{color:var(--muted);font-size:.9em}
main{max-width:var(--maxw);margin:0 auto;padding:24px 18px 60px}
section{margin:28px 0}
.sec-head{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:12px}
.sec-head h2{margin:0}

.site-head{position:sticky;top:0;z-index:10;display:flex;align-items:center;gap:18px;
  justify-content:space-between;padding:12px 18px;background:rgba(14,17,22,.92);
  backdrop-filter:blur(8px);border-bottom:1px solid var(--line)}
.brand a{font-weight:800;letter-spacing:.3px;font-size:1.05rem}
.brand-sub{color:var(--accent);font-weight:600}
.site-nav{display:flex;gap:6px;flex-wrap:wrap}
.site-nav a{padding:7px 12px;border-radius:8px;color:var(--muted);font-weight:600;font-size:.92rem}
.site-nav a:hover{color:var(--text);background:var(--panel)}
.site-nav a.on{color:var(--text);background:var(--panel2)}

.hero{text-align:center;padding:30px 0 6px}
.hero h1{font-size:2.4rem;margin-bottom:.2em}
.hero-sub{color:var(--muted)}
.hero-stage{margin-top:6px}

.cols{display:grid;grid-template-columns:1fr 1fr;gap:24px}
.match-list{display:flex;flex-direction:column;gap:8px}

.match{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.match.has-watched{border-color:var(--accent)}
.m-meta{display:flex;gap:8px;align-items:center;font-size:.78rem;color:var(--muted);margin-bottom:4px}
.m-row{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:10px}
.m-side{display:flex;align-items:center}
.m-side.b{justify-content:flex-end;text-align:right}
.score{font-weight:800;font-size:1.1rem;padding:0 8px}
.pens{font-size:.72rem;color:var(--muted);margin-left:4px}
.vs{color:var(--muted);font-size:.8rem;white-space:nowrap}
.rd{background:var(--panel2);border:1px solid var(--line);border-radius:5px;padding:1px 6px;font-size:.72rem}

.team{display:inline-flex;align-items:center;gap:6px;font-weight:600;border-radius:6px;padding:1px 3px}
.team .fl{font-size:1.1em}
.team.watched{background:rgba(59,130,246,.18);box-shadow:inset 0 0 0 1px var(--accent);font-weight:800}
.slot{display:inline-flex;flex-direction:column;gap:2px}
.slot-label{color:var(--muted);font-weight:600;font-size:.9em}
.slot-cands{display:flex;flex-wrap:wrap;gap:4px}
.cand{font-size:.74rem;background:var(--panel2);border:1px solid var(--line);border-radius:5px;padding:1px 5px}
.cand.watched{border-color:var(--accent);background:rgba(59,130,246,.18);font-weight:700}

.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:6px 6px 4px}
.group-card{padding:0;overflow:hidden}
.group-head{display:flex;justify-content:space-between;align-items:center;padding:10px 14px;border-bottom:1px solid var(--line)}
.group-head h3{margin:0}
table.standings{width:100%;border-collapse:collapse;font-size:.9rem}
.standings th,.standings td{padding:7px 6px;text-align:center}
.standings th{color:var(--muted);font-weight:600;font-size:.74rem;text-transform:uppercase;letter-spacing:.4px}
.standings .tm{text-align:left;width:100%}
.standings td.pos{color:var(--muted);width:22px}
.standings td.pts{font-weight:800}
.standings .gd{color:var(--muted)}
.standings tbody tr{border-top:1px solid var(--line)}
.standings tr.qual td.pos{box-shadow:inset 3px 0 0 var(--green)}
.standings tr.third td.pos{box-shadow:inset 3px 0 0 var(--amber)}
.standings tr.watched{background:rgba(59,130,246,.12)}
.badge{font-size:.68rem;font-weight:700;border-radius:20px;padding:2px 9px;white-space:nowrap}
.badge.win{background:rgba(22,163,74,.18);color:#4ade80}
.badge.q{background:rgba(22,163,74,.12);color:#86efac}
.badge.out{background:rgba(217,119,6,.16);color:var(--gold)}

.group-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:16px}

/* watch button */
.wl{display:inline-flex;align-items:center;gap:6px;cursor:pointer;border-radius:20px;
  border:1px solid var(--line);background:var(--panel2);color:var(--muted);
  font-weight:700;font-size:.82rem;padding:5px 12px}
.wl:hover{color:var(--text);border-color:var(--accent)}
.wl .wl-star{color:var(--muted)}
.wl.on{background:rgba(251,191,36,.16);border-color:var(--gold);color:var(--gold)}
.wl.on .wl-star{color:var(--gold)}

/* team directory cards */
.tcard-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:10px}
.tcard{display:flex;align-items:center;gap:8px;background:var(--panel);border:1px solid var(--line);
  border-left:4px solid var(--accent);border-radius:10px;padding:8px 10px}
.tcard.watched{box-shadow:0 0 0 1px var(--accent)}
.tcard-main{display:flex;align-items:center;gap:10px;flex:1;min-width:0}
.tcard-flag{font-size:1.5rem}
.tcard-body{display:flex;flex-direction:column;min-width:0}
.tcard-name{font-weight:800}
.tcard-meta{font-size:.78rem}
.directory{display:flex;flex-direction:column;gap:18px}
.dir-group .dir-head{font-weight:700;margin-bottom:8px;color:var(--text)}
.team-search{width:100%;max-width:360px;margin-bottom:14px;padding:9px 12px;border-radius:9px;
  border:1px solid var(--line);background:var(--panel);color:var(--text);font-size:.95rem}
.empty{padding:14px;border:1px dashed var(--line);border-radius:10px}

/* team hero */
.team-hero{display:flex;align-items:center;gap:20px;background:linear-gradient(120deg,var(--accent),var(--accent2));
  border-radius:16px;padding:22px 24px;color:#fff;flex-wrap:wrap}
.th-flag{font-size:3.4rem}
.th-main{flex:1;min-width:200px}
.team-hero h1{margin:0;font-size:2rem;color:#fff}
.th-line{margin:4px 0;opacity:.95}
.th-outlook{margin:6px 0 0;font-weight:600}
.th-watch .wl{background:rgba(255,255,255,.16);border-color:rgba(255,255,255,.5);color:#fff}
.th-watch .wl .wl-star{color:#fff}
.th-watch .wl.on{background:#fff;color:#111}
.th-watch .wl.on .wl-star{color:var(--amber)}

.scenarios{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.scenario{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.scenario.third{grid-column:1/-1;border-style:dashed}
.scenario h4{margin:0 0 10px}
.road{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:8px}
.step{display:flex;gap:12px;align-items:flex-start}
.step-rd{display:flex;align-items:center;gap:8px;min-width:140px;font-weight:600;font-size:.85rem;color:var(--muted)}
.step-no{display:inline-grid;place-items:center;min-width:34px;height:24px;padding:0 6px;border-radius:6px;
  background:var(--panel2);border:1px solid var(--line);color:var(--text);font-size:.72rem;font-weight:800}
.step-body{flex:1;border-left:2px solid var(--line);padding:0 0 6px 12px}
.vs-lbl{font-size:.7rem;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}
.step-meta{margin-top:2px}

.bracket-scroll{overflow-x:auto;padding-bottom:10px}
.bracket{display:flex;gap:14px;min-width:max-content}
.br-col{min-width:235px}
.br-col h3{font-size:.95rem;color:var(--muted)}
.bm{background:var(--panel);border:1px solid var(--line);border-radius:9px;padding:8px 10px;margin-bottom:8px}
.bm.has-watched{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent) inset}
.bm-no{font-size:.7rem;color:var(--muted);margin-bottom:4px}
.bm-side{padding:2px 0}
.bm-mid{text-align:center}
.bm-score{font-weight:800}

.site-foot{max-width:var(--maxw);margin:0 auto;padding:24px 18px 50px;border-top:1px solid var(--line);
  display:flex;flex-direction:column;gap:6px}

@media(max-width:760px){
  .focus-grid,.cols,.scenarios{grid-template-columns:1fr}
  .team-hero{flex-direction:column;text-align:center}
  h1{font-size:1.6rem}.hero h1{font-size:1.9rem}
}
"""
