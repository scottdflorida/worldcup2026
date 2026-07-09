"""Home / command-center page: hero, your-teams, Pulse band, the twelve
group tables and the best-third race."""
from __future__ import annotations

from .. import config, data
from ..components import (group_table, pulse_band, star_icon, team_card,
                          team_link)
from ..shell import shell
from ..times import E


def page_home(ctx):
    grid = "".join(group_table(ctx.analyses[g], link_header=True, advance=ctx.advance, knocked=ctx.knocked)
                   for g in sorted(ctx.analyses))
    src = "".join(team_card(ctx, t, rich=True) for t in ctx.teams)

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
    n_played = sum(1 for m in ctx.matches if data.has_result(m))
    n_total = len(ctx.matches)
    pct_played = (n_played / n_total * 100) if n_total else 0

    body = f"""
<section class="hero" aria-label="Tournament status">
  <h1 class="hero-title">THE&nbsp;2026<br><span class="ht-big">WORLD&nbsp;CUP</span><br>IS&nbsp;<span class="ht-live">LIVE</span></h1>
  <div class="hero-foot">
    <div class="hero-prog">
      <div class="hp-head"><span class="hp-k">TOURNAMENT&nbsp;PROGRESS</span><span class="hp-pct">{round(pct_played)}<span class="hp-of">%</span></span></div>
      <div class="tally hero-tally" role="img" aria-label="{n_played} of {n_total} matches played">
        <span class="tally-fill" data-pct="{pct_played:.2f}" style="width:{pct_played:.3f}%"></span>
        <span class="tally-tick" style="left:100%" aria-hidden="true"></span>
      </div>
      <div class="hp-scale"><span>{n_played} of {n_total} matches played</span></div>
    </div>
  </div>
</section>

<section id="your-teams-sec" class="your-teams-sec" data-reveal aria-label="Your teams">
  <div class="sec-head"><h2>Your teams</h2><span class="muted">Pin any team with ★ — next &amp; latest match, lit up everywhere</span></div>
  <div id="your-teams" class="tcard-grid yt-grid"></div>
  <div id="team-src" hidden>{src}</div>
</section>

{pulse_band(ctx)}

<section class="groups-sec" data-reveal aria-label="Groups">
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
    return shell(config.TOURNAMENT["name"] + " — Live Tracker", "index.html", body, ctx,
                 page="index.html")


def _third_in(ctx, r):
    """Whether a third-placed team made the Round of 32 — the actual bracket
    participants once the draw is set, else the provisional points ranking."""
    if getattr(ctx, "ko_resolved", False):
        return r["team"] in ctx.advanced
    return r["qualifies"]
