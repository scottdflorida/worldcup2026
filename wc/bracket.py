"""Knockout bracket resolution and path projection for the focus teams.

The openfootball feed encodes knockout participants as slot tokens:
    1C / 2F        -> winner / runner-up of a group
    3A/B/C/D/F     -> a third-placed team from one of those groups
    W76 / L101     -> winner / loser of match number 76 / 101
This module resolves those tokens against the live standings and traces the
forward path a given team would take toward the final.
"""
from __future__ import annotations

import re

from . import data

GROUP_SLOT = re.compile(r"^([123])([A-L])$")
THIRD_SLOT = re.compile(r"^3((?:[A-L]/)+[A-L])$")
WIN_SLOT = re.compile(r"^W(\d+)$")
LOSE_SLOT = re.compile(r"^L(\d+)$")


def index_matches(matches):
    return {m["num"]: m for m in matches if "num" in m}


def match_winner(match):
    if not data.has_result(match):
        return None
    g1, g2 = data.final_score(match)
    if g1 > g2:
        return match["team1"]
    if g2 > g1:
        return match["team2"]
    return data.penalty_winner(match)  # knockout draw -> penalties


def match_loser(match):
    w = match_winner(match)
    if not w:
        return None
    return match["team2"] if w == match["team1"] else match["team1"]


def _group_key(letter):
    return f"Group {letter}"


def resolve_slot(token, analyses, by_num, _depth=0):
    """Resolve a slot token to a concrete team or a set of candidates.

    Returns dict: team (str|None), decided (bool), label (str), candidates (set).
    """
    token = str(token)

    m = GROUP_SLOT.match(token)
    if m:
        pos = int(m.group(1))
        info = analyses.get(_group_key(m.group(2)))
        if not info:
            return _unknown(token)
        table = info["table"]
        occupant = table[pos - 1]["team"] if len(table) >= pos else None
        if info["complete"] and occupant:
            return {"team": occupant, "decided": True, "label": occupant,
                    "candidates": {occupant}, "slot": token}
        # Provisional: who can still finish at this position?
        cands = {row["team"] for row in table
                 if pos in info["status"].get(row["team"], {}).get("possible_ranks", [])}
        cands = cands or ({occupant} if occupant else set())
        ordinal = {1: "Winner", 2: "Runner-up", 3: "3rd"}[pos]
        label = f"{ordinal} {m.group(2)}"
        return {"team": None, "decided": False, "label": label,
                "candidates": cands, "provisional": occupant, "slot": token}

    m = THIRD_SLOT.match(token)
    if m:
        letters = m.group(1).split("/")
        cands = set()
        for ltr in letters:
            info = analyses.get(_group_key(ltr))
            if info and len(info["table"]) >= 3:
                cands.add(info["table"][2]["team"])
        return {"team": None, "decided": False,
                "label": "3rd " + "/".join(letters),
                "candidates": cands, "slot": token}

    m = WIN_SLOT.match(token)
    if m and _depth < 12:
        src = by_num.get(int(m.group(1)))
        if src is None:
            return _unknown(token)
        w = match_winner(src)
        if w:
            return {"team": w, "decided": True, "label": w, "candidates": {w}, "slot": token}
        c1 = resolve_slot(src["team1"], analyses, by_num, _depth + 1)["candidates"]
        c2 = resolve_slot(src["team2"], analyses, by_num, _depth + 1)["candidates"]
        return {"team": None, "decided": False, "label": f"Winner M{m.group(1)}",
                "candidates": c1 | c2, "slot": token}

    m = LOSE_SLOT.match(token)
    if m and _depth < 12:
        src = by_num.get(int(m.group(1)))
        if src is None:
            return _unknown(token)
        loser = match_loser(src)
        if loser:
            return {"team": loser, "decided": True, "label": loser, "candidates": {loser}, "slot": token}
        c1 = resolve_slot(src["team1"], analyses, by_num, _depth + 1)["candidates"]
        c2 = resolve_slot(src["team2"], analyses, by_num, _depth + 1)["candidates"]
        return {"team": None, "decided": False, "label": f"Loser M{m.group(1)}",
                "candidates": c1 | c2, "slot": token}

    # Already a concrete team name in the feed.
    return {"team": token, "decided": True, "label": token, "candidates": {token}, "slot": token}


def _unknown(token):
    return {"team": None, "decided": False, "label": token, "candidates": set(), "slot": token}


def build_bracket(matches, analyses, focus_teams):
    """Resolve every knockout match into rendered rows grouped by round."""
    by_num = index_matches(matches)
    rounds = {}
    order = ["Round of 32", "Round of 16", "Quarter-final", "Semi-final",
             "Match for third place", "Final"]
    for m in matches:
        rd = m.get("round")
        if rd not in order:
            continue
        t1 = resolve_slot(m["team1"], analyses, by_num)
        t2 = resolve_slot(m["team2"], analyses, by_num)
        focus = set(focus_teams)
        row = {
            "num": m.get("num"),
            "date": m.get("date"),
            "time": m.get("time"),
            "ground": m.get("ground"),
            "team1": t1, "team2": t2,
            "score": m.get("score"),
            "played": data.has_result(m),
            "winner": match_winner(m),
            "touches_focus": bool((t1["candidates"] | t2["candidates"]) & focus),
            "round": rd,
        }
        rounds.setdefault(rd, []).append(row)
    return [(rd, rounds[rd]) for rd in order if rd in rounds]


def forward_map(matches):
    """num -> the match number that consumes this match's winner (W{num})."""
    fmap = {}
    for m in matches:
        for slot in (m.get("team1"), m.get("team2")):
            mm = WIN_SLOT.match(str(slot))
            if mm:
                fmap[int(mm.group(1))] = m["num"]
    return fmap


def _find_r32_with_slot(matches, token):
    out = []
    for m in matches:
        if m.get("round") == "Round of 32" and token in (m.get("team1"), m.get("team2")):
            out.append(m)
    return out


def _find_r32_with_group_third(matches, letter):
    out = []
    for m in matches:
        if m.get("round") != "Round of 32":
            continue
        for slot in (m.get("team1"), m.get("team2")):
            mm = THIRD_SLOT.match(str(slot))
            if mm and letter in mm.group(1).split("/"):
                out.append(m)
    return out


def project_path(team, matches, analyses, group_letter, entry_slot):
    """Trace a team forward from its Round-of-32 entry slot to the final."""
    by_num = index_matches(matches)
    fmap = forward_map(matches)
    entries = _find_r32_with_slot(matches, entry_slot)
    if not entries:
        return None
    cur = entries[0]
    our_token = entry_slot
    steps = []
    seen = set()
    while cur and cur["num"] not in seen:
        seen.add(cur["num"])
        opp_token = cur["team2"] if cur["team1"] == our_token else cur["team1"]
        opp = resolve_slot(opp_token, analyses, by_num)
        steps.append({
            "round": cur["round"], "num": cur["num"], "date": cur.get("date"),
            "ground": cur.get("ground"), "opponent": opp,
        })
        nxt = fmap.get(cur["num"])
        if not nxt:
            break
        our_token = f"W{cur['num']}"
        cur = by_num.get(nxt)
    return steps


def project_team(team, matches, analyses):
    """Build the full projection for a focus team based on current standings."""
    group_letter = None
    for g, info in analyses.items():
        if any(row["team"] == team for row in info["table"]):
            group_letter = g.split()[-1]
            group_info = info
            break
    if not group_letter:
        return None

    table = group_info["table"]
    rank = next(i + 1 for i, row in enumerate(table) if row["team"] == team)
    row = table[rank - 1]
    status = group_info["status"][team]

    # Primary entry slot based on where the team currently sits.
    if rank == 1:
        entry_slot = f"1{group_letter}"
        entry_desc = f"Group {group_letter} winner"
    elif rank == 2:
        entry_slot = f"2{group_letter}"
        entry_desc = f"Group {group_letter} runner-up"
    else:
        entry_slot = None
        entry_desc = f"3rd in Group {group_letter} (would need a best-third spot)"

    path = project_path(team, matches, analyses, group_letter, entry_slot) if entry_slot else None

    # Third-place alternative destinations (where a 3rd-placed team could land).
    third_targets = []
    if rank >= 3 or 3 in status["possible_ranks"]:
        for m in _find_r32_with_group_third(matches, group_letter):
            third_targets.append(m)

    return {
        "team": team,
        "group": f"Group {group_letter}",
        "group_letter": group_letter,
        "rank": rank,
        "row": row,
        "status": status,
        "group_complete": group_info["complete"],
        "entry_slot": entry_slot,
        "entry_desc": entry_desc,
        "path": path,
        "third_targets": [{"num": m["num"], "date": m.get("date"), "ground": m.get("ground")}
                          for m in third_targets],
        "possible_ranks": status["possible_ranks"],
    }
