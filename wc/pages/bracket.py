"""Knockout bracket page: the connected Round-of-32 → Final tree."""
from __future__ import annotations

from .. import config, data
from ..components import side_result, team_link, wl_badge
from ..flags import flag
from ..shell import shell
from ..times import E, _epoch, kickoff_label


# (short label, full round name) per main knockout round, straight from config.
_BRACKET_RAIL = [(config.KO_SHORT[r], r) for r in config.KO_ROUNDS]


def _km_cell(r, ci):
    """One fixed-size match box: a kickoff line and two team rows. No match
    numbers, no 'winner of M…' — unresolved sides fan to their candidate nations
    (the connectors carry the structure)."""
    sides = []
    any_candidate = False
    for key in ("team1", "team2"):
        res = r[key]
        resolved = bool(res["team"])
        if not resolved:
            any_candidate = True
        g = ""
        wl = ""
        code = side_result(r["played"], res["team"], r["winner"])
        is_win = code == "w"
        if r["played"]:
            g1, g2 = data.final_score({"score": r["score"]})
            gv = g1 if key == "team1" else g2
            g = f'<span class="km-g{" kwin" if is_win else " kloss"}">{gv}</span>'
            pens = (r["score"] or {}).get("p")
            if pens:
                pv = pens[0] if key == "team1" else pens[1]
                g += f'<span class="km-pen{" kwin" if is_win else ""}">({pv})</span>'
            # A plain W/L tag — the clearest at-a-glance read of who advanced.
            wl = wl_badge(code)
        side_cls = "km-team" + ("" if resolved else " is-candidate") + \
                   ((" kw" if is_win else " kl") if r["played"] else "")
        sides.append(f'<div class="{side_cls}">{_bracket_side(res)}{g}{wl}</div>')
    km_cls = "km" + (" km-live" if any_candidate and ci == 0 else "") + \
             (" km-done" if r["played"] else "")
    when = kickoff_label(r) or '<span class="ko"><span class="ko-day">TBD</span></span>'
    return (
        f'<div class="{km_cls}" data-mnum="{r["num"]}">'
        f'<div class="km-when">{when}</div>'
        f'{sides[0]}'
        f'<div class="km-line"><span class="km-wire wire"><span class="wire-pulse"></span></span></div>'
        f'{sides[1]}</div>'
    )


def _bracket_side(res):
    """A bracket slot: a resolved nation, or the set of teams that could fill it.

    Never shows 'Winner of M…'. Two or fewer candidates read as named chips; more
    collapse to a flags row (names hidden via CSS). The box grows to show them all."""
    if res["team"]:
        return team_link(res["team"], "bteam")
    prov = res.get("provisional")
    if prov:  # group still in progress: show who currently holds the slot
        return (f'{team_link(prov, "bteam prov")}'
                f'<span class="bcode" title="current table position">{E(res.get("slot",""))}</span>')
    cands = sorted(res.get("candidates") or [])
    if not cands:
        return '<span class="bslot muted">TBD</span>'
    chips = "".join(team_link(c, "bcand") for c in cands)
    cls = "bcands" + (" many" if len(cands) > 2 else "")
    return f'<span class="{cls}" data-n="{len(cands)}">{chips}</span>'


def _bronze_side(res):
    """Compact bronze-match side: the resolved semi-final loser, its (≤2) candidate
    losers as chips, or a terse placeholder while the semis are still deep in
    candidates — keeps the mini-card small on the plinth."""
    if res["team"]:
        return team_link(res["team"], "bteam")
    cands = sorted(res.get("candidates") or [])
    if 1 <= len(cands) <= 2:
        return "".join(team_link(c, "bcand") for c in cands)
    return '<span class="bslot muted">T.B.D.</span>'


def _bronze_card(r):
    """The third-place (bronze) match as a compact card seated beneath the champion
    plinth. Carries the shared data-live / data-ts / data-team hooks so the
    generalised [data-live] poller lights it up once both semi-final losers are
    known (its two sides are L-token candidates until the semis decide)."""
    t1, t2 = r["team1"], r["team2"]
    played = r["played"]
    code1 = side_result(played, t1["team"], r["winner"])
    code2 = side_result(played, t2["team"], r["winner"])
    s1 = (f'<span class="cpb-side{" won" if code1 == "w" else ""}">'
          f'{_bronze_side(t1)}{wl_badge(code1)}</span>')
    s2 = (f'<span class="cpb-side b{" won" if code2 == "w" else ""}">'
          f'{wl_badge(code2)}{_bronze_side(t2)}</span>')
    if played:
        g1, g2 = data.final_score({"score": r["score"]})
        mid = (f'<span class="cpb-mid" data-live-mid>'
               f'<b class="sg{" win" if code1 == "w" else ""}">{g1}</b>'
               f'<span class="sdash">–</span>'
               f'<b class="sg{" win" if code2 == "w" else ""}">{g2}</b></span>')
    else:
        mid = '<span class="cpb-mid vs" data-live-mid>v</span>'
    when = kickoff_label(r) or '<span class="ko"><span class="ko-day">TBD</span></span>'
    live = bool(t1["team"] and t2["team"]) and not played
    live_attr = f' data-live data-date="{E(r.get("date",""))}"' if live else ""
    tag = '<span class="cpb-tag" data-live-tag hidden></span>' if live else ""
    return (
        f'<div class="cp-bronze{" is-done" if played else ""}" data-mnum="{r["num"]}" '
        f'data-ts="{_epoch(r)}"{live_attr} aria-label="Third-place match">'
        f'<div class="cpb-k">BRONZE{tag}</div>'
        f'<div class="cpb-when">{when}</div>'
        f'<div class="cpb-row">{s1}{mid}{s2}</div></div>'
    )


def page_bracket(ctx):
    rounds = [(rd, rows) for rd, rows in ctx.bracket if rd != "Match for third place"]
    bronze_row = next((rows[0] for rd, rows in ctx.bracket
                       if rd == "Match for third place" and rows), None)
    n_round = len(rounds)
    cols = []
    for ci, (rd, rows) in enumerate(rounds):
        is_final = rd == "Final"
        cells = "".join(_km_cell(r, ci) for r in rows)
        if is_final:
            final_row = rows[0] if rows else None
            if final_row and final_row["played"] and final_row.get("winner"):
                champ_team = final_row["winner"]
                champ = (f'<div class="champ-name" data-team="{E(champ_team)}">'
                         f'<span class="fl">{flag(champ_team)}</span>'
                         f'<span class="nm">{E(champ_team)}</span></div>')
            else:
                champ = '<div class="champ-name pending muted">Champion T.B.D.</div>'
            bronze = _bronze_card(bronze_row) if bronze_row else ""
            plinth = (
                '<div class="champion-plinth">'
                '<img class="cp-trophy" src="assets/trophy.svg" alt="" width="40" height="40" aria-hidden="true">'
                '<div class="cp-lbl">World Champion</div>'
                f'{champ}{bronze}</div>'
            )
            cols.append(
                f'<div class="kr-col kr-final">'
                f'<div class="kr-head"><img class="kr-trophy" src="assets/trophy.svg" alt="" width="18" height="18" aria-hidden="true">{E(rd)}</div>'
                f'<div class="kr-body">{cells}{plinth}</div></div>'
            )
        else:
            cols.append(
                f'<div class="kr-col"><div class="kr-head">{E(rd)} '
                f'<span class="kr-count">{len(rows)}</span></div>'
                f'<div class="kr-body">{cells}</div></div>'
            )

    stage = ctx.stage()
    # The bronze final isn't a rail round; while it's the live stage keep the rail
    # anchored on the Final (the last column) rather than falling back to R32.
    rail_stage = "Final" if stage == "Third-place match" else stage
    active = next((i for i, (_, key) in enumerate(_BRACKET_RAIL) if key == rail_stage), 0)
    rail_items = "".join(
        f'<span class="brn-item{" on" if i == active else ""}" data-rd="{i}">{E(short)}</span>'
        for i, (short, _) in enumerate(_BRACKET_RAIL))

    body = f"""
<section class="bracket-intro" aria-label="Knockout bracket">
  <h1>Knockout bracket</h1>
  <p class="muted">Round of 32 → Final as one connected tree. Pin teams with ★ to mark their path.</p>
  <div class="bracket-rail" aria-label="Bracket rounds">
    <span class="brn-label">Current round:</span>
    <div class="bracket-rail-nav">{rail_items}</div>
  </div>
</section>
<div class="bracket-frame at-start" data-bracket>
  <span class="bz-edge-l" aria-hidden="true"></span>
  <span class="bz-edge-r" aria-hidden="true"></span>
  <div class="bracket-wrap" data-hscroll>
    <div class="kbracket" data-rounds="{n_round}">
      <svg class="bz-layer" aria-hidden="true"></svg>
      {"".join(cols)}
    </div>
  </div>
</div>
"""
    return shell("Knockout Bracket — World Cup 2026", "bracket.html", body, ctx,
                 desc="The full 2026 World Cup knockout bracket as one connected tree, "
                      "Round of 32 to the Final — with live candidates before slots resolve "
                      "and your pinned teams glowing through.",
                 page="bracket.html")
