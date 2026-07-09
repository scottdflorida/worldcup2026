"""Fantasy bracket page + the pick-able knockout data structure."""
from __future__ import annotations

import json

from .. import bracket, config, data
from ..components import _FB_RND
from ..flags import flag
from ..shell import shell
from ..times import E, _utc_iso, kickoff_label


def fantasy_data(ctx):
    """The knockout tree as a pick-able structure: every match with its feeders
    (or R32 entrants) and any winner already locked by a real result. The client
    builds the picker options from this — a slot's feasible teams are its feeders'
    picked/locked occupants, or, while those are open, their whole candidate pool."""
    by_num = ctx.by_num
    fmap = bracket.forward_map(ctx.matches)
    rev = {}
    for a, b in fmap.items():
        rev.setdefault(b, []).append(a)
    keys = bracket.tree_order_keys(ctx.matches)
    matches, order = {}, {"L": {}, "R": {}, "F": []}
    for rd in config.KO_ROUNDS:
        ms = sorted([m for m in ctx.matches if m.get("round") == rd],
                    key=lambda m: keys.get(m["num"], 10 ** 9))
        rkey, half = _FB_RND[rd], len(ms) // 2
        for i, m in enumerate(ms):
            num = m["num"]
            side = "F" if rd == "Final" else ("L" if i < half else "R")
            entry = {"round": rkey, "side": side,
                     "winner": bracket.match_winner(m) if data.has_result(m) else None}
            if rd == "Round of 32":
                ents = []
                for slot in (m["team1"], m["team2"]):
                    r = bracket.resolve_slot(slot, ctx.analyses, by_num)
                    ents.append({"team": r["team"]} if r["team"]
                                else {"pool": sorted(r["candidates"])})
                entry["entrants"] = ents
            else:
                entry["feeders"] = sorted(rev.get(num, []), key=lambda n: keys.get(n, 10 ** 9))
            matches[str(num)] = entry
            (order["F"].append(num) if side == "F"
             else order[side].setdefault(rkey, []).append(num))
    # Third-place (bronze) match: pickable like any other tie. app.js's feasible()
    # only reads an `entrants` pool for a match tagged round "R32", so the bronze
    # node borrows that tag and is handed the two semi-final LOSERS (resolve_slot
    # on its L-tokens -> concrete loser, or the candidate pool while the semis are
    # open). It's rendered as a standalone box beside the Final, never in the tree.
    tp = next((mm for mm in ctx.matches if mm.get("round") == "Match for third place"), None)
    if tp is not None:
        ents = []
        for slot in (tp["team1"], tp["team2"]):
            r = bracket.resolve_slot(slot, ctx.analyses, by_num)
            ents.append({"team": r["team"]} if r["team"] else {"pool": sorted(r["candidates"])})
        matches[str(tp["num"])] = {
            "round": "R32", "side": "F", "third": True,
            "winner": bracket.match_winner(tp) if data.has_result(tp) else None,
            "entrants": ents,
        }
        order["third"] = tp["num"]
    teams = set()
    for e in matches.values():
        if e.get("winner"):
            teams.add(e["winner"])
        for ent in e.get("entrants", []):
            teams.update([ent["team"]] if ent.get("team") else ent.get("pool", []))
    return {"matches": matches, "order": order, "flags": {t: flag(t) for t in sorted(teams)}}


def _fb_box(num, e):
    """One winner-slot box for a match (every round, including the R32) — empty
    until the client fills it; shows the locked winner for a settled tie."""
    champ = " fb-champ" if e["round"] == "F" else ""
    locked = " fb-locked" if e.get("winner") else ""
    return (f'<div class="fb-node fb-pick fb-empty{champ}{locked}" data-m="{num}" data-round="{e["round"]}">'
            '<button class="fb-slot" type="button" aria-label="Pick winner">'
            '<span class="fb-fl"></span></button></div>')


def _fb_entrants_col(r32_nums, matches):
    """The outer flag layer: the two qualified teams that feed each R32 box, in
    tree order, so every R32 box sits midway between its pair."""
    cells = []
    for num in r32_nums:
        for ent in matches[str(num)]["entrants"]:
            if ent.get("team"):
                t = ent["team"]
                cells.append(f'<div class="fb-ent" data-r32="{num}" data-team="{E(t)}" '
                             f'title="{E(t)}"><span class="fb-fl">{flag(t)}</span></div>')
            else:  # still a candidate pool (e.g. an unresolved 3rd place)
                cells.append(f'<div class="fb-ent fb-ent-tbd" data-r32="{num}"><span class="fb-fl">·</span></div>')
    return f'<div class="fb-col fb-entrants" data-round="ENT">{"".join(cells)}</div>'


def _fb_col(rkey, nums, matches):
    cells = "".join(_fb_box(n, matches[str(n)]) for n in nums)
    return f'<div class="fb-col" data-round="{rkey}">{cells}</div>'


def _fb_upcoming(ctx, n=4):
    """A short list of the next n knockout matches still to be played, each with
    its sides (or TBD) and tz-aware kickoff — shown beneath the bracket."""
    by_num = ctx.by_num
    ko = [m for m in ctx.matches
          if m.get("round") in config.KO_ROUNDS
          and not data.has_result(m) and _utc_iso(m)]
    ko.sort(key=lambda m: _utc_iso(m) or "9999")

    def side(slot):
        r = bracket.resolve_slot(slot, ctx.analyses, by_num)
        if r["team"]:
            return f'<span class="fbu-team">{flag(r["team"])} {E(r["team"])}</span>'
        return '<span class="fbu-team tbd muted">TBD</span>'

    rows = []
    for mm in ko[:n]:
        rows.append(
            f'<li class="fbu-row">'
            f'<div class="fbu-teams">{side(mm["team1"])}<span class="fbu-v">v</span>{side(mm["team2"])}</div>'
            f'<div class="fbu-meta"><span class="fbu-rd">{_FB_RND.get(mm.get("round"), "")}</span>'
            f'<span class="fbu-when">{kickoff_label(mm)}</span></div></li>')
    if not rows:
        return ""
    return ('<section class="fbu" aria-label="Upcoming matches">'
            '<div class="sec-head"><h2>Upcoming</h2><span class="muted">next four matches</span></div>'
            f'<ul class="fbu-list">{"".join(rows)}</ul></section>')


def page_fantasy(ctx):
    fb = fantasy_data(ctx)
    m, od = fb["matches"], fb["order"]
    lr32, rr32 = od["L"].get("R32", []), od["R"].get("R32", [])
    left = (_fb_entrants_col(lr32, m)
            + "".join(_fb_col(rk, od["L"].get(rk, []), m) for rk in ("R32", "R16", "QF", "SF")))
    right = ("".join(_fb_col(rk, od["R"].get(rk, []), m) for rk in ("SF", "QF", "R16", "R32"))
             + _fb_entrants_col(rr32, m))
    final_inner = "".join(_fb_box(n, m[str(n)]) for n in od["F"])
    third_num = od.get("third")
    if third_num is not None:
        final_inner += ('<div class="fb-third">'
                        '<span class="fb-third-k">Third place</span>'
                        + _fb_box(third_num, m[str(third_num)]) + '</div>')
    final = f'<div class="fb-col fb-final-col" data-round="F">{final_inner}</div>'
    body = f"""
<section class="fb-intro" aria-label="Fantasy bracket">
  <div class="fb-head"><h1>Fantasy bracket</h1>
    <button id="fb-reset" class="fb-reset" type="button">Reset</button></div>
  <p class="muted">Tap to pick a winner in every undecided tie — settled results are locked. Saved on this device.</p>
</section>
<div class="fb-wrap" aria-label="Knockout bracket">
  <div class="fb">
    <svg class="fb-lines" aria-hidden="true"><path d=""/></svg>
    <div class="fb-side fb-left">{left}</div>
    {final}
    <div class="fb-side fb-right">{right}</div>
  </div>
</div>
{_fb_upcoming(ctx)}
<div class="fb-modal" id="fb-modal" hidden>
  <div class="fb-modal-back" data-fb-close></div>
  <div class="fb-modal-panel" role="dialog" aria-modal="true" aria-label="Pick the winner">
    <div class="fb-modal-head"><span class="fb-modal-k">Pick the winner</span>
      <button class="fb-modal-x" type="button" data-fb-close aria-label="Close">✕</button></div>
    <div class="fb-modal-grid" id="fb-modal-grid"></div>
    <button class="fb-modal-clear" type="button" data-fb-clear>Clear this pick</button>
  </div>
</div>
<script>window.FB_DATA={json.dumps(fb, ensure_ascii=False, separators=(",", ":"))};</script>
"""
    return shell("Fantasy Bracket — World Cup 2026", "fantasy.html", body, ctx,
                 desc="Fill in your own 2026 World Cup knockout bracket — a compact, flags-only "
                      "picker where every undecided tie is yours to call.",
                 page="fantasy.html")
