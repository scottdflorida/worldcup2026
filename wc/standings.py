"""Group standings, FIFA tiebreakers, and qualification (clinch) analysis."""
from __future__ import annotations

import itertools
import random
from collections import defaultdict

from . import data


def _blank(team):
    return {
        "team": team, "P": 0, "W": 0, "D": 0, "L": 0,
        "GF": 0, "GA": 0, "GD": 0, "Pts": 0,
    }


def _apply(stats, team1, team2, g1, g2):
    s1, s2 = stats[team1], stats[team2]
    s1["P"] += 1; s2["P"] += 1
    s1["GF"] += g1; s1["GA"] += g2
    s2["GF"] += g2; s2["GA"] += g1
    if g1 > g2:
        s1["W"] += 1; s2["L"] += 1; s1["Pts"] += 3
    elif g2 > g1:
        s2["W"] += 1; s1["L"] += 1; s2["Pts"] += 3
    else:
        s1["D"] += 1; s2["D"] += 1; s1["Pts"] += 1; s2["Pts"] += 1
    s1["GD"] = s1["GF"] - s1["GA"]
    s2["GD"] = s2["GF"] - s2["GA"]


def group_matches(matches):
    """Return {group_name: [match, ...]} for the 12 group-stage groups."""
    groups = defaultdict(list)
    for m in matches:
        g = m.get("group")
        if g:
            groups[g].append(m)
    return dict(sorted(groups.items()))


def _stats_from(group_ms, include=None):
    """Build per-team stats. `include` optionally restricts to a subset of matches."""
    teams = set()
    for m in group_ms:
        teams.add(m["team1"]); teams.add(m["team2"])
    stats = {t: _blank(t) for t in teams}
    for m in (include if include is not None else group_ms):
        if data.has_result(m):
            g1, g2 = data.final_score(m)
            _apply(stats, m["team1"], m["team2"], g1, g2)
    return stats


def rank_teams(stats, played_matches):
    """Order teams by FIFA group tiebreakers (display ranking).

    1) points  2) goal difference  3) goals for
    4) head-to-head among teams still tied: points, GD, GF in matches between them
    5) (fair play / drawing of lots — not modelled; falls back to team name)
    """
    teams = list(stats.values())

    def overall_key(s):
        return (s["Pts"], s["GD"], s["GF"])

    teams.sort(key=lambda s: overall_key(s) + (s["team"],), reverse=True)
    # Resolve blocks tied on (Pts, GD, GF) with a head-to-head mini-table.
    ordered = []
    i = 0
    while i < len(teams):
        j = i
        while j + 1 < len(teams) and overall_key(teams[j + 1]) == overall_key(teams[i]):
            j += 1
        block = teams[i:j + 1]
        if len(block) > 1:
            block = _head_to_head(block, played_matches)
        ordered.extend(block)
        i = j + 1
    return ordered


def _head_to_head(block, played_matches):
    names = {s["team"] for s in block}
    mini = {t: _blank(t) for t in names}
    for m in played_matches:
        if m["team1"] in names and m["team2"] in names and data.has_result(m):
            g1, g2 = data.final_score(m)
            _apply(mini, m["team1"], m["team2"], g1, g2)
    return sorted(
        block,
        key=lambda s: (mini[s["team"]]["Pts"], mini[s["team"]]["GD"], mini[s["team"]]["GF"], s["team"]),
        reverse=True,
    )


def _outcomes(remaining):
    """All win/draw/loss combinations for the remaining matches (3 per match)."""
    return itertools.product((0, 1, 2), repeat=len(remaining))


def analyze_group(group_ms):
    """Compute current table plus conservative clinch/elimination status.

    Clinch logic is points-only and tie-conservative: whenever two teams could
    finish level on points we treat *both* orderings as possible, so a badge is
    only shown when it is true for every remaining scoreline.
    """
    played = [m for m in group_ms if data.has_result(m)]
    remaining = [m for m in group_ms if not data.has_result(m)]
    teams = sorted({t for m in group_ms for t in (m["team1"], m["team2"])})

    # Display table from results so far.
    cur_stats = _stats_from(group_ms)
    table = rank_teams(cur_stats, played)

    # Enumerate remaining outcomes for points-based position bounds.
    possible = {t: set() for t in teams}
    # Share of remaining-result combinations that leave each team in each final
    # position (1st..4th). Equal weighting per combo; point-ties split evenly
    # across the tied positions. Used for the per-group scenario visualisation.
    dist = {t: [0.0] * len(teams) for t in teams}
    base_pts = {t: cur_stats[t]["Pts"] for t in teams}
    ncombos = 0
    for combo in _outcomes(remaining):
        ncombos += 1
        pts = dict(base_pts)
        for outcome, m in zip(combo, remaining):
            if outcome == 0:      # team1 win
                pts[m["team1"]] += 3
            elif outcome == 1:    # draw
                pts[m["team1"]] += 1; pts[m["team2"]] += 1
            else:                 # team2 win
                pts[m["team2"]] += 3
        for t in teams:
            more = sum(1 for o in teams if o != t and pts[o] > pts[t])
            fewer = sum(1 for o in teams if o != t and pts[o] < pts[t])
            best_rank = more + 1
            worst_rank = len(teams) - fewer
            possible[t].update(range(best_rank, worst_rank + 1))
            span = worst_rank - best_rank + 1
            for r in range(best_rank, worst_rank + 1):
                dist[t][r - 1] += 1.0 / span
    if ncombos:
        for t in teams:
            dist[t] = [x / ncombos for x in dist[t]]

    status = {}
    for t in teams:
        ranks = possible[t]
        status[t] = {
            "won_group": ranks == {1},
            "clinched_top2": max(ranks) <= 2,
            "can_top2": min(ranks) <= 2,
            "eliminated_top2": min(ranks) >= 3,
            "eliminated": min(ranks) >= 3 and not _can_be_best_third_possible(),
            "possible_ranks": sorted(ranks),
        }

    return {
        "group": group_ms[0]["group"],
        "table": table,
        "complete": len(remaining) == 0,
        "remaining": len(remaining),
        "status": status,
        "dist": dist,
        "scenarios": ncombos,
    }


def _can_be_best_third_possible():
    # Third place may still advance via the eight best third-placed teams; we do
    # not hard-eliminate a third-placed side here (that needs cross-group info).
    return True


def all_groups(matches):
    gms = group_matches(matches)
    return {g: analyze_group(ms) for g, ms in gms.items()}


def best_thirds(group_analyses):
    """Rank the 12 third-placed teams (provisional until group stage ends).

    Returns list of dicts with team, group, stats and a `qualifies` flag for the
    current top eight.
    """
    thirds = []
    for g, info in group_analyses.items():
        if len(info["table"]) >= 3:
            row = info["table"][2]
            thirds.append({"group": g, **row})
    thirds.sort(key=lambda r: (r["Pts"], r["GD"], r["GF"], r["team"]), reverse=True)
    for i, r in enumerate(thirds):
        r["qualifies"] = i < 8
        r["seed"] = i + 1
    return thirds


def advance_probabilities(matches, analyses=None, n_sims=20000, seed=20260611):
    """Monte-Carlo chance each team reaches the knockouts (top 2 OR a best-third).

    Simulates every remaining group match (equal-likely win/draw/loss, with a
    plausible random scoreline for goal-difference tiebreaks), ranks all 12
    groups, then takes the eight best third-placed teams — exactly the real
    qualification rule. Seeded so the published numbers are stable between
    builds on the same data.
    """
    gms = group_matches(matches)
    groups_data = {}
    all_teams = []
    for g, ms in gms.items():
        teams = sorted({t for m in ms for t in (m["team1"], m["team2"])})
        st = _stats_from(ms)
        base = {t: (st[t]["Pts"], st[t]["GF"], st[t]["GA"]) for t in teams}
        remaining = [m for m in ms if not data.has_result(m)]
        groups_data[g] = (teams, base, remaining)
        all_teams.extend(teams)

    rng = random.Random(seed)
    counts = {t: 0 for t in all_teams}
    for _ in range(n_sims):
        thirds = []
        for teams, base, remaining in groups_data.values():
            pts = {t: base[t][0] for t in teams}
            gf = {t: base[t][1] for t in teams}
            ga = {t: base[t][2] for t in teams}
            for m in remaining:
                a, b = m["team1"], m["team2"]
                r = rng.random()
                if r < 1 / 3:        # a wins
                    s1 = rng.randint(1, 3); s2 = rng.randint(0, s1 - 1)
                elif r < 2 / 3:      # draw
                    s1 = s2 = rng.randint(0, 2)
                else:                # b wins
                    s2 = rng.randint(1, 3); s1 = rng.randint(0, s2 - 1)
                gf[a] += s1; ga[a] += s2; gf[b] += s2; ga[b] += s1
                if s1 > s2:
                    pts[a] += 3
                elif s2 > s1:
                    pts[b] += 3
                else:
                    pts[a] += 1; pts[b] += 1
            order = sorted(teams, key=lambda t: (pts[t], gf[t] - ga[t], gf[t], rng.random()),
                           reverse=True)
            counts[order[0]] += 1
            counts[order[1]] += 1
            t3 = order[2]
            thirds.append((pts[t3], gf[t3] - ga[t3], gf[t3], rng.random(), t3))
        thirds.sort(reverse=True)
        for entry in thirds[:8]:
            counts[entry[4]] += 1

    return {t: counts[t] / n_sims for t in all_teams}


def team_group(matches, team):
    for g, ms in group_matches(matches).items():
        teams = {t for m in ms for t in (m["team1"], m["team2"])}
        if team in teams:
            return g
    return None
