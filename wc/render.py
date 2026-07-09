"""Render the static site (multi-page) from the live data + computed analyses.

Pages: a live "command center" home, per-group detail (with scenario viz), a team
hub for every nation, a searchable team directory, and a connected knockout
bracket. The site is team-agnostic — visitors pin any team(s) via a client-side
watchlist that lights them up everywhere ("Live Wire" continuity).

This module is the orchestrator: it owns the shared Context, wires together the
page builders in wc/pages/, and writes the files. The building blocks live in
focused modules — time helpers (wc/times.py), shared HTML fragments
(wc/components.py), page chrome (wc/shell.py), frontend assets (wc/art.py) and
one module per page (wc/pages/). Design system, motion and all client behavior
are emitted from the assets under wc/assets/ (single source of truth).
"""
from __future__ import annotations

import json
import os

from . import art, blurbs, bracket, config, data, i18n, ics, pages, squads, standings, util


class Context:
    def __init__(self, payload):
        self.payload = payload
        self.matches = payload["matches"]
        # One match-number index, shared by every builder (match_line, the Pulse
        # band, calendar, fantasy, betting, team roads) instead of each rebuilding it.
        self.by_num = bracket.index_matches(self.matches)
        self.analyses = standings.all_groups(self.matches)
        self.thirds = standings.best_thirds(self.analyses)
        self.bracket = bracket.build_bracket(self.matches, self.analyses)
        self.teams = sorted({row["team"] for i in self.analyses.values() for row in i["table"]})
        self.projections = {t: bracket.project_team(t, self.matches, self.analyses)
                            for t in self.teams}
        self.advance = standings.advance_probabilities(self.matches, self.analyses)
        self.last_updated = data.last_updated()
        self.blurbs = blurbs.load_cache()   # LLM road-to-final write-ups (may be empty)
        self.squads = squads.load_cache()   # ESPN rosters keyed by team (may be empty)
        self._wire_knockout()

    def _wire_knockout(self):
        """Once the bracket draw is set, the Round-of-32 participants ARE the teams
        that advanced — the authoritative truth (group winners, runners-up and the
        eight best thirds all in one place). Capture it, then mark every other team
        in a finished group as knocked out so badges and tables reflect reality
        without re-deriving the cross-group best-third allocation."""
        by_num = self.by_num
        advanced = set()
        for m in self.matches:
            if m.get("round") == "Round of 32":
                for slot in (m.get("team1"), m.get("team2")):
                    res = bracket.resolve_slot(slot, self.analyses, by_num)
                    if res["team"]:
                        advanced.add(res["team"])
        self.advanced = advanced
        # The draw is "known" once enough slots resolve to real nations (24 group
        # winners + runners-up at minimum); before then we don't claim eliminations.
        self.ko_resolved = len(advanced) >= 24
        self.knocked = set()
        if not self.ko_resolved:
            return
        for info in self.analyses.values():
            if not info["complete"]:
                continue
            for t, st in info["status"].items():
                st["advanced"] = t in advanced
                if t not in advanced:
                    st["eliminated"] = True
                    self.knocked.add(t)

    def knocked_out(self, team):
        """True when a team's group is finished and it did NOT make the bracket."""
        return self.ko_resolved and team not in self.advanced and team in self.teams

    def team_fixtures(self, team):
        """(next_match, recent_match) for a team across group + knockout play,
        counting only games it is CONFIRMED in (resolved by name), newest-relevant
        first. Either may be None."""
        mine = [m for m in self.sorted_matches()
                if team in (m.get("team1"), m.get("team2"))]
        nxt = next((m for m in mine if not data.has_result(m)), None)
        recent = next((m for m in reversed(mine) if data.has_result(m)), None)
        return nxt, recent

    def next_match(self, team):
        """The team's next unplayed fixture as (match, opponent, round_label), or
        None. Falls back to the projected bracket path so a side that has advanced
        into a knockout slot still carried as a winner token (not yet named in the
        feed) still surfaces its next match — with the opponent as a live candidate
        set when it isn't decided yet."""
        nxt, _ = self.team_fixtures(team)
        by_num = self.by_num
        if nxt is not None:
            opp_token = nxt["team2"] if nxt.get("team1") == team else nxt["team1"]
            return nxt, bracket.resolve_slot(opp_token, self.analyses, by_num), nxt.get("round", "")
        if self.knocked_out(team):
            return None
        proj = self.projections.get(team)
        if not proj:
            return None
        g = proj["group_letter"]
        entry = f'{proj["rank"]}{g}' if proj["rank"] in (1, 2) else None
        path = bracket.project_path(team, self.matches, self.analyses, g, entry) or []
        for step in path:
            m = by_num.get(step["num"])
            if m is not None and not data.has_result(m):
                return m, step["opponent"], step["round"]
        return None

    def sorted_matches(self):
        return sorted(self.matches, key=lambda m: (m.get("date", ""), m.get("time", "")))

    def recent_results(self, n=6):
        return [m for m in self.sorted_matches() if data.has_result(m)][-n:][::-1]

    def upcoming(self, n=6):
        return [m for m in self.sorted_matches() if not data.has_result(m)][:n]

    def stage(self):
        if not all(i["complete"] for i in self.analyses.values()):
            return "Group stage"
        # Walk the full knockout order (bronze final sits between the semis and
        # the Final) so the tournament reports "Third-place match" on Jul 16–18
        # rather than jumping straight to "Final".
        for rd in config.KO_ROUNDS_ALL:
            ms = [m for m in self.matches if m.get("round") == rd]
            if ms and not all(data.has_result(m) for m in ms):
                return "Third-place match" if rd == "Match for third place" else rd
        return "Final"

    def thirds_resolvable(self):
        """The 8-best-third allocation is only meaningful once every group is
        complete; until then we render a labeled provisional state (no fabricated
        qualifiers)."""
        return all(i["complete"] for i in self.analyses.values())



# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
def render_site(payload):
    # Fresh asset fingerprint for THIS render (memoized across every shell()
    # call below); recomputed here so it reflects the current i18n.js bytes.
    art._asset_ver_cache = None
    ctx = Context(payload)
    files = {
        "index.html": pages.page_home(ctx),
        "teams.html": pages.page_teams(ctx),
        "bracket.html": pages.page_bracket(ctx),
        "fantasy.html": pages.page_fantasy(ctx),
        "betting.html": pages.page_betting(ctx),
        "bets-data.json": json.dumps(pages.betting_data(ctx), ensure_ascii=False, separators=(",", ":")),
        "calendar.html": pages.page_calendar(ctx),
        "assets/style.css": art.STYLE,
        "assets/app.js": art.APP_JS,
        "assets/i18n.js": i18n.build_js(),
        "assets/ball.svg": art.BALL_SVG,
        "assets/trophy.svg": art.TROPHY_SVG,
        "assets/favicon.svg": art.FAVICON_SVG,
        "assets/og.svg": art.OG_SVG,
    }
    for g in ctx.analyses:
        letter = g.split()[-1]
        files[f"group-{letter.lower()}.html"] = pages.page_group(ctx, letter)
    for team in ctx.teams:
        files[util.page_for(team)] = pages.page_team(ctx, team)
    # Subscribable calendars: the full schedule + one feed per nation. These live
    # under public/ics/ (write_site only clears *.html, so they persist/overwrite).
    files["ics/all-matches.ics"] = ics.all_matches_ics(ctx)
    for team in ctx.teams:
        files[f"ics/{util.slug(team)}.ics"] = ics.team_ics(ctx, team)
    return files


def write_site(public_dir, payload):
    """Render and write the site, clearing stale HTML pages first."""
    files = render_site(payload)
    if os.path.isdir(public_dir):
        for fn in os.listdir(public_dir):
            if fn.endswith(".html"):
                os.remove(os.path.join(public_dir, fn))
    for rel, content in files.items():
        out = os.path.join(public_dir, rel)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(content)
    return len(files)
