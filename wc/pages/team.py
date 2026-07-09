"""Per-nation team hub: hero, group standings, the branching road-to-the-final
graph, fixtures and squad."""
from __future__ import annotations

from .. import blurbs, bracket, data, i18n, squads, util
from ..components import (_ordinal, _round_short, group_decided, group_table,
                          json_island, match_line, match_list, star, team_link)
from ..flags import flag
from ..shell import shell
from ..times import E, kickoff_label


def _ko_entry_heading(proj, cur):
    """Headline for a team's confirmed knockout road (how it entered the bracket)."""
    g = proj["group"]
    if cur == 1:
        return f"{g} winners"
    if cur == 2:
        return f"{g} runners-up"
    return "Through as a best third"


_SEP = '<span class="ths-sep">·</span>'


def _hero_opp(opp):
    """Opponent fragment for the hero status: a resolved nation, its ≤2 live
    candidate opponents, or a terse 'opponent TBD' when the slot is wide open."""
    if opp["team"]:
        return f'v {team_link(opp["team"], "ths-opp")}'
    cands = sorted(opp.get("candidates") or [])
    if 1 <= len(cands) <= 2:
        return "v " + " / ".join(team_link(c, "cand") for c in cands)
    return '<span class="ths-tbd">opponent TBD</span>'


def _hero_status(ctx, team, proj):
    """The team hero's leading status line — the CURRENT tournament state, driven
    by the live bracket, never the frozen group framing.

    Returns (kicker, detail_html, tone):
      kicker  -> eyebrow word/round (uppercased by CSS; emitted in i18n dict form
                 so pt-BR translates it).
      detail  -> the HTML status detail (may be "").
      tone    -> 'alive' | 'out' | 'champ' | '' (drives the hero treatment).
    """
    # Champion / runners-up: the Final has been decided.
    final_m = next((m for m in ctx.matches if m.get("round") == "Final"), None)
    if final_m is not None and data.has_result(final_m):
        if bracket.match_winner(final_m) == team:
            return ("World champions",
                    '<span class="ths-txt">Winners of the 2026 World Cup</span>', "champ")
        if bracket.match_loser(final_m) == team:
            return ("Runners-up", '<span class="ths-txt">Lost in the final</span>', "out")

    # Alive, with a scheduled next match (group or knockout).
    nm = ctx.next_match(team)
    if nm is not None:
        m, opp, rd = nm
        is_group = str(rd).startswith("Matchday")
        # A team that has finished its group games but whose group isn't settled
        # yet only projects SPECULATIVELY into the Round of 32 — don't invent
        # knockout text before the bracket is real; fall back to group framing.
        if not is_group and not proj["group_complete"]:
            return ("Group stage", "", "alive")
        parts = [_hero_opp(opp)]
        ko = kickoff_label(m)
        if ko:
            parts.append(f'<span class="ths-when">{ko}</span>')
        kicker = "Group stage" if is_group else rd
        return (kicker, f' {_SEP} '.join(parts), "alive")

    # No next match -> the run is over. Group-stage exit?
    if ctx.knocked_out(team):
        return ("Knocked out",
                '<span class="ths-txt">Out in the group stage</span>', "out")

    # Otherwise knocked out in the knockouts — surface the losing game.
    _, recent = ctx.team_fixtures(team)
    if recent is not None:
        rd_short = _round_short(recent.get("round", ""))
        g1, g2 = data.final_score(recent)
        home = recent.get("team1") == team
        our, their = (g1, g2) if home else (g2, g1)
        opp_name = recent.get("team2") if home else recent.get("team1")
        opp_link = team_link(opp_name, "ths-opp") if opp_name else "TBD"
        pens = (recent.get("score") or {}).get("p")
        pen_html = ""
        if pens:
            pt_, po_ = (pens[0], pens[1]) if home else (pens[1], pens[0])
            pen_html = f' <span class="ths-pens">({pt_}–{po_} pens)</span>'
        detail = (f'<span class="ths-rd">{E(rd_short)}</span> {_SEP} '
                  f'<span class="ths-score">{our}–{their}</span>{pen_html} v {opp_link}')
        return ("Knocked out", detail, "out")

    return ("", "", "")


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
    by_num = ctx.by_num
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


def _team_hero(team, proj, g, pr, sec, kicker, status_detail, tone):
    """The status-toned team hero (rebuilt in Phase 0) — kept intact here."""
    tone_cls = f" {tone}" if tone else ""
    status_line = f'<p class="th-status">{status_detail}</p>' if status_detail else ""
    return f"""
<section class="team-hero{tone_cls}" data-team="{E(team)}" style="--accent:{pr};--accent2:{sec}">
  <div class="th-inner">
    <div class="th-flag" aria-hidden="true">{flag(team)}</div>
    <div class="th-main">
      <div class="th-eyebrow">{E(kicker)}</div>
      <h1>{E(team)}</h1>
      {status_line}
      <p class="th-line"><a class="th-grp" href="group-{g.lower()}.html">{E(proj['group'])}</a> · {_ordinal(proj['rank'])} place · {proj['row']['Pts']} pts ({proj['row']['W']}W {proj['row']['D']}D {proj['row']['L']}L)</p>
    </div>
    <div class="th-watch">{star(team, "Watch")}</div>
  </div>
</section>
"""


def _standings_section(ctx, info, proj):
    """Group standings. Once the group is decided this is history: the table shows
    the qualification outcome (group_table), so the caption drops the odds framing."""
    sub = ("how the group finished" if group_decided(info)
           else "your team highlighted · advance odds as a tally")
    return f"""
<section aria-label="Group standings">
  <div class="sec-head"><h2>{E(proj['group'])} standings</h2><span class="muted">{sub}</span></div>
  {group_table(info, solo=True, advance=ctx.advance, knocked=ctx.knocked)}
</section>
"""


def _next_fixture(ctx, m):
    """The next scheduled fixture promoted as a prominent bar — kickoff, venue and
    the opponent (or its live candidate set). Reuses match_line so it stays
    live-wired and cross-page consistent (same round codes, v/vs separators)."""
    rd = m.get("round", "")
    # Knockout ties get their short code in the accent slot; group games already
    # carry their group + matchday inside the match line, so leave it bare.
    rd_lbl = "" if str(rd).startswith("Matchday") else _round_short(rd)
    rd_chip = f'<span class="nk-rd">{E(rd_lbl)}</span>' if rd_lbl else ""
    return (
        '<div class="next-ko" data-reveal>'
        f'<div class="nk-head"><span class="nk-k">Next match</span>{rd_chip}</div>'
        f'{match_line(m, ctx)}</div>'
    )


def _road_graph(roads, third_html, knocked):
    """The road graph body: the projected/played branches, or a terse note when a
    team has no bracket path. Collapses to one column for a lone road (no hole)."""
    solo = len(roads) == 1 and not third_html
    if roads or third_html:
        return (f'<div class="roads{" solo" if solo else ""}">'
                f'{"".join(roads)}{third_html}</div>')
    if knocked:
        return '<p class="muted">Knocked out — the road ended in the group stage this time.</p>'
    return '<p class="muted">No knockout path yet — the bracket opens once the group stage ends.</p>'


def _blurb_html(ctx, team):
    b = blurbs.blurb_for(ctx.blurbs, team)
    if not b:
        return ''
    # Ship ONLY this team's pt-BR blurb, as a JSON island the i18n runtime merges
    # into its dict at init (kept out of the global i18n.js payload). No island when
    # there's no fingerprint-matching translation → pt mode falls back to English.
    pt = i18n.blurb_pt_for(team)
    isl = json_island("wc-pt-blurb", pt) if pt else ''
    return f'<p class="road-blurb">{E(b)}</p>{isl}'


def _ics_row(team):
    """A quiet 'SUBSCRIBE (.ics)' link to this team's fixture feed, tucked under
    the road section's header."""
    href = f"ics/{util.slug(team)}.ics"
    return (f'<div class="ics-row"><a class="ics-sub" href="{href}" '
            f'title="Subscribe to {E(team)} fixtures">SUBSCRIBE (.ics)</a></div>')


def _road_section(ctx, team, roads, third_html):
    """ALIVE team: the road AHEAD. Lead with the next fixture, then the projected
    path (candidate fans until each tie resolves). No results/standings here — the
    campaign so far follows below."""
    nm = ctx.next_match(team)
    next_box = _next_fixture(ctx, nm[0]) if nm is not None else ""
    return f"""
<section aria-label="Road to the final">
  <div class="sec-head"><h2>Road to the final</h2><span class="muted">potential futures — who {E(team)} could meet each round</span></div>
  {_ics_row(team)}
  {_blurb_html(ctx, team)}
  {next_box}
  {_road_graph(roads, third_html, knocked=False)}
</section>
"""


def _results_section(ctx, mine_played, gr_upcoming):
    """ALIVE team: results so far (group + knockout together). While the group is
    still running, the remaining group games sit alongside; once it's done there is
    no empty second column."""
    results = (f'<div class="match-list">{match_list(mine_played, ctx, "None yet")}</div>')
    if gr_upcoming:
        return (
            '<section class="cols" aria-label="Fixtures">'
            f'<div><h2 class="col-h">Results</h2>{results}</div>'
            '<div><h2 class="col-h">Remaining group games</h2>'
            f'<div class="match-list">{match_list(gr_upcoming, ctx)}</div></div>'
            '</section>'
        )
    return (
        '<section aria-label="Results">'
        '<div class="sec-head"><h2>Results</h2><span class="muted">their run so far</span></div>'
        f'{results}</section>'
    )


def _campaign_section(ctx, team, mine_played, roads, third_html, knocked, champ):
    """ELIMINATED (or CHAMPION) team: the finished campaign. The full results
    timeline — group games through the decisive knockout match — comes first, then
    the road graph in past-tense form. No 'potential futures', no empty
    remaining-games column (see usa.html)."""
    sub = "the run to the title" if champ else "how their World Cup unfolded"
    return f"""
<section aria-label="Their tournament">
  <div class="sec-head"><h2>Their tournament</h2><span class="muted">{sub}</span></div>
  {_ics_row(team)}
  {_blurb_html(ctx, team)}
  <div class="camp-results"><h3 class="col-h">Results</h3>
    <div class="match-list">{match_list(mine_played, ctx, "None yet")}</div></div>
  {_road_graph(roads, third_html, knocked)}
</section>
"""


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
        # The draw is set: trace the one real road (played rounds + future fans).
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

    # Full match timeline for this team across group + knockout play (by name),
    # chronological — group games first, ending on the most recent (or fatal) tie.
    mine = [m for m in ctx.sorted_matches() if team in (m.get("team1"), m.get("team2"))]
    mine_played = [m for m in mine if data.has_result(m)]
    # Remaining GROUP games only; the next knockout tie is featured in the road.
    gr_upcoming = [m for m in mine if not data.has_result(m)
                   and str(m.get("round", "")).startswith("Matchday")]

    # The hero status drives the whole page's SECTION ORDER, not just the header.
    kicker, status_detail, tone = _hero_status(ctx, team, proj)
    done = tone in ("out", "champ")        # a finished campaign (eliminated or won)
    champ = tone == "champ"

    hero = _team_hero(team, proj, g, pr, sec, kicker, status_detail, tone)
    standings = _standings_section(ctx, info, proj)
    squad = squad_section(ctx, team)

    if done:
        # ELIMINATED: campaign (results incl. the fatal tie, then the past road),
        # then the group standings as history, then the squad. CHAMPION rides the
        # same order — the road simply ends in the Final win (trivial, commented).
        body = hero + _campaign_section(ctx, team, mine_played, roads, third_html,
                                        knocked, champ) + standings + squad
    else:
        # ALIVE: lead with the road ahead (next fixture + projected path), then the
        # results so far, then the group standings (history now), then the squad.
        body = (hero + _road_section(ctx, team, roads, third_html)
                + _results_section(ctx, mine_played, gr_upcoming) + standings + squad)

    return shell(f"{team} — Road to the Final · World Cup 2026", "teams.html", body, ctx,
                 desc=(f"{team} at the 2026 World Cup: where they stand, what they need "
                       f"to advance, and their potential road to the final. Pin {team} "
                       f"with ★ to follow them everywhere."),
                 page=util.page_for(team),
                 crumb=[("Teams", "teams.html"), (team, None)])
