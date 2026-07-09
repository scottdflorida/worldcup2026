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

from . import config, data

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


def tree_order_keys(matches):
    """Order knockout matches as a bracket *tree*, not by match number.

    Returns {match_num: sort_key}. Sorting each round's matches by this key lays
    the bracket out so the two games feeding a given next-round game sit directly
    above/below it — consecutive pairs in one column feed one game in the next —
    which is exactly what the column layout and the connector lines assume.
    """
    by_num = index_matches(matches)
    prev_round = {b: a for a, b in zip(config.KO_ROUNDS, config.KO_ROUNDS[1:])}

    def feeders(m):
        # Each side is either a W{n} edge or — once that feeder match is played —
        # the winner's actual NAME (the feed overwrites the token). Recover the
        # edge in the played case so the tree ordering doesn't lose a branch and
        # shift every later pairing by one.
        out = []
        pr = prev_round.get(m.get("round"))
        for slot in (m.get("team1"), m.get("team2")):
            mm = WIN_SLOT.match(str(slot))
            if mm and int(mm.group(1)) in by_num:
                out.append(int(mm.group(1)))
            elif pr:
                for cand in matches:
                    if cand.get("round") == pr and match_winner(cand) == slot:
                        out.append(cand["num"])
                        break
        return out

    # Depth-first from the Final, numbering Round-of-32 leaves in tree order.
    leaf_idx = {}
    counter = [0]

    def number_leaves(num, depth=0):
        m = by_num.get(num)
        if m is None or depth > 12:
            return
        kids = feeders(m)
        if not kids:
            if num not in leaf_idx:
                leaf_idx[num] = counter[0]
                counter[0] += 1
            return
        for k in kids:
            number_leaves(k, depth + 1)

    root = next((m["num"] for m in matches
                 if m.get("round") == "Final" and "num" in m), None)
    if root is not None:
        number_leaves(root)
    # Defensive: any leaf not reachable from the Final gets a trailing index.
    for m in sorted(matches, key=lambda x: x.get("num", 0)):
        n = m.get("num")
        if n is not None and not feeders(m) and n not in leaf_idx:
            leaf_idx[n] = counter[0]
            counter[0] += 1

    def min_leaf(num, depth=0):
        m = by_num.get(num)
        if m is None or depth > 12:
            return leaf_idx.get(num, 10 ** 9)
        kids = feeders(m)
        if not kids:
            return leaf_idx.get(num, 10 ** 9)
        return min(min_leaf(k, depth + 1) for k in kids)

    return {m["num"]: min_leaf(m["num"]) for m in matches if "num" in m}


def build_bracket(matches, analyses):
    """Resolve every knockout match into rendered rows grouped by round."""
    by_num = index_matches(matches)
    rounds = {}
    order = config.KO_ROUNDS_ALL
    for m in matches:
        rd = m.get("round")
        if rd not in order:
            continue
        t1 = resolve_slot(m["team1"], analyses, by_num)
        t2 = resolve_slot(m["team2"], analyses, by_num)
        row = {
            "num": m.get("num"),
            "date": m.get("date"),
            "time": m.get("time"),
            "ground": m.get("ground"),
            "team1": t1, "team2": t2,
            "score": m.get("score"),
            "played": data.has_result(m),
            "winner": match_winner(m),
            "round": rd,
        }
        rounds.setdefault(rd, []).append(row)
    keys = tree_order_keys(matches)
    return [(rd, sorted(rounds[rd], key=lambda r: keys.get(r["num"], 10 ** 9)))
            for rd in order if rd in rounds]


def forward_map(matches):
    """num -> the match number that consumes this match's winner (W{num}).

    The feed encodes the edge as a W{num} token, but overwrites it with the
    actual winner's NAME once a match is played — which would erase the edge and
    snap a team's road mid-tournament. So we also recover played edges by finding
    where each played match's winner reappears in the next round.
    """
    fmap = {}
    for m in matches:
        for slot in (m.get("team1"), m.get("team2")):
            mm = WIN_SLOT.match(str(slot))
            if mm:
                fmap[int(mm.group(1))] = m["num"]
    nxt_round = dict(zip(config.KO_ROUNDS, config.KO_ROUNDS[1:]))
    for m in matches:
        num = m.get("num")
        if num is None or num in fmap:
            continue
        w = match_winner(m)
        target_round = nxt_round.get(m.get("round"))
        if not w or not target_round:
            continue
        for cand in matches:
            if cand.get("round") == target_round and w in (cand.get("team1"), cand.get("team2")):
                fmap[num] = cand["num"]
                break
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


def _our_side(match, our_ids):
    """Given the tokens that identify our team in `match`, return the OTHER side's
    token, or None if our team isn't actually in this match (we lost / unknown)."""
    t1, t2 = str(match.get("team1")), str(match.get("team2"))
    if t1 in our_ids:
        return match.get("team2")
    if t2 in our_ids:
        return match.get("team1")
    return None


def find_ko_match(matches, team):
    """The Round-of-32 match a team is confirmed into (by name), once the group
    stage has resolved its slot token to the actual nation. None pre-knockout."""
    for m in matches:
        if m.get("round") == "Round of 32" and team in (m.get("team1"), m.get("team2")):
            return m
    return None


def project_path(team, matches, analyses, group_letter, entry_slot):
    """Trace a team forward from its Round-of-32 entry to the final.

    Robust to the feed resolving slot tokens ('1C') into nation names ('Brazil')
    once a group finishes: we enter by NAME when the draw is set, otherwise by the
    provisional slot token, and identify ourselves at each subsequent round by
    either the carried W{num} edge or our resolved name.
    """
    by_num = index_matches(matches)
    fmap = forward_map(matches)

    cur = find_ko_match(matches, team)
    if cur is not None:
        our_ids = {team}
    elif entry_slot:
        entries = _find_r32_with_slot(matches, entry_slot)
        if not entries:
            return None
        cur = entries[0]
        our_ids = {entry_slot, team}
    else:
        return None

    steps = []
    seen = set()
    while cur and cur["num"] not in seen:
        seen.add(cur["num"])
        opp_token = _our_side(cur, our_ids)
        if opp_token is None:
            break
        opp = resolve_slot(opp_token, analyses, by_num)
        step = {
            "round": cur["round"], "num": cur["num"], "date": cur.get("date"),
            "time": cur.get("time"), "ground": cur.get("ground"), "opponent": opp,
            "played": data.has_result(cur),
        }
        if step["played"]:
            # Orient the score to our team (feed carries concrete names once played).
            g1, g2 = data.final_score(cur)
            home = cur.get("team1") == team
            our, their = (g1, g2) if home else (g2, g1)
            step["score"] = f"{our}–{their}"
            step["won"] = match_winner(cur) == team
            pens = (cur.get("score") or {}).get("p")
            if pens:
                pt_, po_ = (pens[0], pens[1]) if home else (pens[1], pens[0])
                step["pens"] = f"{pt_}–{po_}"
                step["won"] = pt_ > po_
        steps.append(step)
        # Stop at a loss: the team is out, so don't follow the winner-edge into
        # later rounds (that path belongs to whoever beat them). The road ends on
        # the game they lost.
        if step["played"] and not step.get("won"):
            break
        nxt = fmap.get(cur["num"])
        if not nxt:
            break
        # In the next round we appear either as the winner-edge token or, once the
        # match is played and we advanced, by our own name.
        our_ids = {f"W{cur['num']}", team}
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
