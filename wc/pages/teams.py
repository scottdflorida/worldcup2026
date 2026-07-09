"""Searchable directory of all 48 nations, grouped, with your-teams rail."""
from __future__ import annotations

from ..components import team_card
from ..shell import shell
from ..times import E


def page_teams(ctx):
    directory = []
    for g in sorted(ctx.analyses):
        info = ctx.analyses[g]
        cards = "".join(team_card(ctx, row["team"]) for row in info["table"])
        directory.append(
            f'<div class="dir-group"><div class="dir-head">'
            f'<a href="group-{g.split()[-1].lower()}.html">{E(g)}</a> '
            f'<span class="muted">{"Final" if info["complete"] else str(info["remaining"]) + " to play"}</span></div>'
            f'<div class="tcard-grid">{cards}</div></div>'
        )
    src = "".join(team_card(ctx, t, rich=True) for t in ctx.teams)
    body = f"""
<section class="teams-intro" aria-label="All teams">
  <h1>All 48 teams</h1>
  <p class="muted">Tap a team to inspect its path to the final; ★ to follow it across the site.</p>
</section>
<section id="your-teams-sec" class="your-teams-sec" data-reveal aria-label="Your teams">
  <div class="sec-head"><h2>Your teams</h2><span class="muted">Pin any team with ★ — next &amp; latest match, lit up everywhere</span></div>
  <div id="your-teams" class="tcard-grid yt-grid"></div>
  <div id="team-src" hidden>{src}</div>
</section>
<section id="directory" aria-label="Team directory">
  <div class="search-wrap">
    <span class="search-ic" aria-hidden="true">⌕</span>
    <input id="team-search" class="team-search" type="search" placeholder="Search any of 48 teams…" aria-label="Search teams">
  </div>
  <p id="search-empty" class="muted search-empty" hidden>No teams match that search.</p>
  <div class="directory">{"".join(directory)}</div>
</section>
"""
    return shell("All Teams — World Cup 2026", "teams.html", body, ctx,
                 desc="Browse and search all 48 nations at the 2026 World Cup. Open any "
                      "team's hub for standings, advance odds and road to the final.",
                 page="teams.html")
