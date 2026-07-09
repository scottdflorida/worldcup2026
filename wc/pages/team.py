"""Per-nation team hub: hero, group standings, the branching road-to-the-final
graph, fixtures and squad."""
from __future__ import annotations

from .. import blurbs, bracket, data, squads, util
from ..components import (_ordinal, _round_short, group_table, match_line,
                          match_list, star, team_link)
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
