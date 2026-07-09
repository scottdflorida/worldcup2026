"""Per-group detail page: standings, finish scenarios and fixtures."""
from __future__ import annotations

from .. import data
from ..components import dist_section, group_table, match_list, team_link
from ..shell import shell
from ..times import E


def page_group(ctx, letter):
    g = f"Group {letter}"
    info = ctx.analyses[g]
    ms = sorted([m for m in ctx.matches if m.get("group") == g],
                key=lambda m: (m.get("date", ""), m.get("time", "")))
    completed = [m for m in ms if data.has_result(m)]
    upcoming = [m for m in ms if not data.has_result(m)]
    chips = " ".join(team_link(row["team"]) for row in info["table"])
    state = "Final standings" if info["complete"] else f'{info["remaining"]} games to play'
    body = f"""
<section class="group-banner">
  <div class="gb-letter">{E(letter)}</div>
  <div class="gb-main"><div class="gb-tag">Group stage</div>
    <h1 class="gb-title">Group {E(letter)}</h1>
    <div class="gb-state">{E(state)}</div>
    <div class="gb-teams">{chips}</div></div>
</section>

<section aria-label="Standings">
  <div class="sec-head"><h2>Standings</h2><span class="muted">live table · advance odds as a tally</span></div>
  {group_table(info, solo=True, advance=ctx.advance, knocked=ctx.knocked)}
</section>

<section aria-label="Scenarios">
  <div class="sec-head"><h2>Scenarios</h2><span class="muted">how the remaining games could finish the table</span></div>
  {dist_section(info, ctx.advance)}
</section>

<section aria-label="Upcoming games"><div class="sec-head"><h2>Coming up</h2></div>
  <div class="match-list">{match_list(upcoming, ctx, "Group complete")}</div></section>

<section aria-label="Completed games"><div class="sec-head"><h2>Results</h2></div>
  <div class="match-list">{match_list(completed, ctx, "None played yet")}</div></section>
"""
    return shell(f"Group {letter} — World Cup 2026", "", body, ctx,
                 desc=(f"Group {letter} at the 2026 World Cup: live standings, advance "
                       f"odds, finish scenarios, fixtures and scorers."),
                 page=f"group-{letter.lower()}.html",
                 crumb=[("Groups", "index.html#groups"), (f"Group {letter}", None)])
