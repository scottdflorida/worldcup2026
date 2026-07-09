"""Home / command-center page — phase-aware.

The layout is driven by the tournament stage the engine already computes, in three
explicit modes (the branch in `page_home` reads in one screen):

  GROUPS MODE   (group stage running) — hero + progress, Your Teams, Matchday
                Pulse, the twelve group tables and the best-third race.
  KNOCKOUT MODE (bracket running)     — hero carrying the current round + next
                kickoff, a large next/live scorebug with the round's schedule
                beside it, a compact bracket rail, status-aware Your Teams, and
                the settled group stage collapsed to one archive strip.
  CHAMPION MODE (final decided)       — hero states the champions; the rest as
                knockout mode. Deliberately simple; not fixture-testable yet.
"""
from __future__ import annotations

from .. import bracket, config, data
from ..components import (archive_band, bracket_rail, group_table, pulse_band,
                          round_ribbon, scorebug, star_icon, team_link,
                          teams_island, _champion, _round_full, _slot_name)
from ..flags import flag
from ..shell import shell
from ..times import E, kickoff_label


def page_home(ctx):
    champ = _champion(ctx)
    if ctx.stage() == "Group stage":
        body = _mode_groups(ctx)
    elif champ:
        body = _mode_champion(ctx, champ)
    else:
        body = _mode_knockout(ctx)
    return shell(config.TOURNAMENT["name"] + " — Live Tracker", "index.html", body, ctx,
                 page="index.html")


# --------------------------------------------------------------------------
# Stage helpers
# --------------------------------------------------------------------------
def _current_round(ctx):
    """(round_name, [matches]) for the earliest knockout round with an unplayed
    game — the round the tournament is currently contesting. ("", []) when the
    group stage is still running or every knockout match is done."""
    for rd in config.KO_ROUNDS_ALL:
        ms = [m for m in ctx.sorted_matches() if m.get("round") == rd]
        if ms and not all(data.has_result(m) for m in ms):
            return rd, ms
    return "", []


def _next_match_of(round_ms):
    """The earliest unplayed match of a round (the one to promote), or None."""
    up = sorted((m for m in round_ms if not data.has_result(m)),
                key=lambda m: (m.get("date", ""), m.get("time", "")))
    return up[0] if up else None


# --------------------------------------------------------------------------
# Shared fragments
# --------------------------------------------------------------------------
def _hero_progress(ctx):
    n_played = sum(1 for m in ctx.matches if data.has_result(m))
    n_total = len(ctx.matches)
    pct = (n_played / n_total * 100) if n_total else 0
    return f"""<div class="hero-foot">
    <div class="hero-prog">
      <div class="hp-head"><span class="hp-k">TOURNAMENT&nbsp;PROGRESS</span><span class="hp-pct">{round(pct)}<span class="hp-of">%</span></span></div>
      <div class="tally hero-tally" role="img" aria-label="{n_played} of {n_total} matches played">
        <span class="tally-fill" data-pct="{pct:.2f}" style="width:{pct:.3f}%"></span>
        <span class="tally-tick" style="left:100%" aria-hidden="true"></span>
      </div>
      <div class="hp-scale"><span>{n_played} of {n_total} matches played</span></div>
    </div>
  </div>"""


def _hero(ctx, now=""):
    """The type-led hero. `now` is the optional current-round supporting line
    (knockout mode); the big headline + progress tally are shared across stages."""
    return f"""
<section class="hero" aria-label="Tournament status">
  <h1 class="hero-title">THE&nbsp;2026<br><span class="ht-big">WORLD&nbsp;CUP</span><br>IS&nbsp;<span class="ht-live">LIVE</span></h1>
  {now}
  {_hero_progress(ctx)}
</section>
"""


def _hero_now(ctx, rd, nxt):
    """The hero's supporting line: CURRENT ROUND · FIXTURE · KICKOFF, in the
    established mono style (e.g. QUARTER-FINALS · FRANCE v MOROCCO · THU 13:00 PT)."""
    by_num = ctx.by_num
    t1 = bracket.resolve_slot(nxt["team1"], ctx.analyses, by_num)
    t2 = bracket.resolve_slot(nxt["team2"], ctx.analyses, by_num)
    ko = kickoff_label(nxt)
    ko_html = (f'<span class="hn-sep" aria-hidden="true">·</span>'
               f'<span class="hn-ko">{ko}</span>') if ko else ""
    return (f'<p class="hero-now">'
            f'<span class="hn-rd">{E(_round_full(rd))}</span>'
            f'<span class="hn-sep" aria-hidden="true">·</span>'
            f'<span class="hn-fix">{_slot_name(t1, "hn-tm")}'
            f'<span class="hn-v"> v </span>{_slot_name(t2, "hn-tm")}</span>'
            f'{ko_html}</p>')


def _your_teams(ctx, status=False):
    return f"""
<section id="your-teams-sec" class="your-teams-sec" data-reveal aria-label="Your teams">
  <div class="sec-head"><h2>Your teams</h2><span class="muted">Pin any team with ★ — next &amp; latest match, lit up everywhere</span></div>
  <div id="your-teams" class="tcard-grid yt-grid"></div>
  {teams_island(ctx, status)}
</section>
"""


def _scorebug_section(ctx, rd, round_ms, nxt):
    """The next/live match promoted to a large scorebug band, with the rest of the
    current round as a reflowed Pulse ribbon beside/under it."""
    if nxt is None:
        return ""
    n_up = sum(1 for m in round_ms if not data.has_result(m))
    others = [m for m in sorted(round_ms, key=lambda m: (m.get("date", ""), m.get("time", "")))
              if m is not nxt]
    return f"""
<section class="ko-next" data-reveal aria-label="Next match">
  <div class="sec-head"><h2>Next up</h2><span class="muted"><span>{E(_round_full(rd))}</span> · <span>{n_up} to play</span></span></div>
  {scorebug(ctx, nxt)}
  {round_ribbon(ctx, others)}
</section>
"""


# --------------------------------------------------------------------------
# Modes
# --------------------------------------------------------------------------
def _mode_knockout(ctx):
    rd, round_ms = _current_round(ctx)
    nxt = _next_match_of(round_ms)
    return (
        _hero(ctx, now=_hero_now(ctx, rd, nxt) if nxt is not None else "")
        + _scorebug_section(ctx, rd, round_ms, nxt)
        + bracket_rail(ctx, rd)
        + _your_teams(ctx, status=True)
        + archive_band(ctx)
    )


def _mode_champion(ctx, champ):
    # Final decided: lead with the champions; the bracket rail shows the completed
    # final and the rest mirrors knockout mode. Kept deliberately simple — there is
    # no live scorebug once the tournament is won (nothing is "next"). Not yet
    # fixture-testable (no completed-final fixture exists).
    hero = f"""
<section class="hero hero-champ" aria-label="Champions">
  <h1 class="hero-title"><span class="hc-flag" aria-hidden="true">{flag(champ)}</span>{E(champ)}<br><span class="ht-live">World champions</span></h1>
  {_hero_progress(ctx)}
</section>
"""
    rd, _round_ms = _current_round(ctx)  # "" once every match is played
    return (
        hero
        + bracket_rail(ctx, rd or "Final")
        + _your_teams(ctx, status=True)
        + archive_band(ctx)
    )


def _mode_groups(ctx):
    """Group stage running — the original command-center layout, preserved."""
    grid = "".join(group_table(ctx.analyses[g], link_header=True, advance=ctx.advance, knocked=ctx.knocked)
                   for g in sorted(ctx.analyses))

    resolvable = ctx.thirds_resolvable()
    # Best-third allocation race rendered as the Tally device: each team's points
    # as a fraction of the strongest third-placed side, with a hard threshold tick
    # at the 8th-best cutoff (the line eight teams must clear to advance).
    _tpts = [r["Pts"] for r in ctx.thirds]
    _tmax = max(_tpts) if _tpts else 1
    _tmax = _tmax or 1
    _cut = sorted(_tpts, reverse=True)[7] if len(_tpts) >= 8 else (min(_tpts) if _tpts else 0)
    _cut_pct = (_cut / _tmax * 100) if _tmax else 0
    thirds_rows = "".join(
        f'<tr class="{"qual" if (resolvable and _third_in(ctx, r)) else ""}" data-team="{E(r["team"])}">'
        f'<td class="pos">{r["seed"]}</td><td class="star">{star_icon(r["team"])}</td>'
        f'<td class="tm">{team_link(r["team"])}</td>'
        f'<td>{E(r["group"].split()[-1])}</td><td>{r["Pts"]}</td><td class="gd">{r["GD"]:+d}</td><td>{r["GF"]}</td>'
        f'<td class="race">'
        f'<span class="tally mini-tally" data-pct="{(r["Pts"]/_tmax*100):.2f}" title="{r["Pts"]} pts">'
        f'<span class="tally-fill" style="width:{(r["Pts"]/_tmax*100):.3f}%"></span>'
        f'<span class="tally-tick" style="left:{_cut_pct:.3f}%" aria-hidden="true" title="8th-best cutoff"></span></span></td>'
        f'<td class="r32">{(("✓ in" if _third_in(ctx, r) else "out") if resolvable else "—")}</td></tr>'
        for r in ctx.thirds
    )
    thirds_state = "resolved" if resolvable else "provisional"
    thirds_note = ("Eight third-placed teams advance to the Round of 32."
                   if resolvable else
                   "Provisional — the eight best third-placed teams are fixed once "
                   "every group finishes. This race updates as groups conclude.")

    return f"""
{_hero(ctx)}

{_your_teams(ctx)}

{pulse_band(ctx)}

<section id="groups" class="groups-sec" data-reveal aria-label="Groups">
  <div class="sec-head"><h2>The twelve groups</h2><span class="muted">Tap a group for fixtures &amp; scenarios</span></div>
  <div class="group-grid">{grid}</div>
</section>

<section class="thirds-sec" data-reveal data-thirds-state="{thirds_state}" aria-label="Best third-placed teams">
  <div class="sec-head"><h2>Best third-placed race</h2><span class="muted">{"eight advance" if resolvable else "provisional · eight will advance"}</span></div>
  <div class="card thirds-card"><table class="standings thirds">
  <thead><tr><th>Seed</th><th aria-label="Watch"></th><th class="tm">Team</th><th>Grp</th><th>Pts</th><th>GD</th><th>GF</th><th class="race-h">Race&nbsp;to&nbsp;8th</th><th>R32</th></tr></thead>
  <tbody>{thirds_rows}</tbody></table>
  <p class="muted dist-note">{thirds_note}</p></div>
</section>
"""


def _third_in(ctx, r):
    """Whether a third-placed team made the Round of 32 — the actual bracket
    participants once the draw is set, else the provisional points ranking."""
    if getattr(ctx, "ko_resolved", False):
        return r["team"] in ctx.advanced
    return r["qualifies"]
