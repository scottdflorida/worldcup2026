"""National-team squads (players + positions) for every World Cup team, pulled
from ESPN's public site API and cached in data/squads.json.

For each team we fetch the roster (jersey, position line, age) and then look at
their most recent COMPLETED match to mark the starting XI — so the team page can
group the squad by line and highlight who actually started last time out.

render.page_team reads the cache only; teams without data simply show no squad.
Every network call is best-effort — any failure leaves the cache untouched and
the build proceeds, exactly like odds.py.
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone

from . import util

LEAGUE = "fifa.world"
BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/%s" % LEAGUE
SQUADS_PATH = "data/squads.json"
TTL_HOURS = 20  # squads change rarely — refresh about once a day

# ESPN display names whose slug doesn't match our openfootball name.
ALIASES = {
    "bosnia-herzegovina": "Bosnia & Herzegovina",
    "congo-dr": "DR Congo",
    "czechia": "Czech Republic",
    "turkiye": "Turkey",
    "united-states": "USA",
}

# position line -> display order + heading
POS_ORDER = {"G": 0, "D": 1, "M": 2, "F": 3}
POS_NAME = {"G": "Goalkeepers", "D": "Defenders", "M": "Midfielders", "F": "Forwards"}


def _get(url, timeout=25):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _team_index(our_teams):
    """Map our team name -> ESPN team id, via slug with a handful of aliases."""
    our = {util.slug(t): t for t in our_teams}
    idx = {}
    d = _get(BASE + "/teams")
    for t in d["sports"][0]["leagues"][0]["teams"]:
        nm = t["team"]["displayName"]
        s = util.slug(nm)
        ours = our.get(s) or ALIASES.get(s)
        if ours:
            idx[ours] = t["team"]["id"]
    return idx


def _starter_jerseys(eid, log):
    """(jersey numbers, match label) of the XI this team last started.

    Walks their schedule newest-first and reads the first completed match whose
    summary exposes a starting XI for this side. Empty set if none is available.
    """
    try:
        sch = _get(BASE + "/teams/%s/schedule" % eid)
    except Exception as e:  # noqa: BLE001
        log("[squads]   schedule %s failed (%r)" % (eid, e))
        return set(), ""
    done = [e for e in sch.get("events", [])
            if (e.get("competitions", [{}])[0].get("status", {})
                .get("type", {}).get("completed"))]
    done.sort(key=lambda e: e.get("date") or "", reverse=True)  # most recent first
    for e in done:
        try:
            summ = _get(BASE + "/summary?event=%s" % e.get("id"))
        except Exception:  # noqa: BLE001 — skip this match, try an older one
            continue
        for side in (summ.get("rosters") or []):
            if str((side.get("team") or {}).get("id")) != str(eid):
                continue
            jerseys = {str(p.get("jersey")) for p in side.get("roster", [])
                       if p.get("starter") and p.get("jersey") is not None}
            if jerseys:
                return jerseys, e.get("name", "")
    return set(), ""


def _squad(eid, log):
    d = _get(BASE + "/teams/%s/roster" % eid)
    starters, as_of = _starter_jerseys(eid, log)
    players = []
    for a in d.get("athletes", []):
        num = a.get("jersey")
        players.append({
            "num": num,
            "name": a.get("displayName"),
            "pos": (a.get("position") or {}).get("abbreviation") or "",
            "age": a.get("age"),
            "starter": bool(num is not None and str(num) in starters),
        })
    players.sort(key=lambda p: (
        POS_ORDER.get(p["pos"], 9),
        0 if p["starter"] else 1,
        int(p["num"]) if str(p.get("num") or "").isdigit() else 999,
        p["name"] or "",
    ))
    return {"players": players, "as_of": as_of}


def load_cache(path=SQUADS_PATH):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def squad_for(cache, team):
    """The squad record for a team, or None."""
    return (cache or {}).get("teams", {}).get(team)


def refresh(our_teams, path=SQUADS_PATH, *, force=False, log=print):
    """Refetch every squad if the cache is missing/stale. Returns squads written."""
    cur = load_cache(path)
    if not force and cur.get("fetched_at"):
        try:
            age = (datetime.now(timezone.utc)
                   - datetime.fromisoformat(cur["fetched_at"])).total_seconds()
            if age < TTL_HOURS * 3600:
                log("[squads] cache fresh (%dh old) — skipping" % (age // 3600))
                return 0
        except ValueError:
            pass
    idx = _team_index(our_teams)
    teams = {}
    for name, eid in sorted(idx.items()):
        try:
            sq = _squad(eid, log)
            if sq["players"]:
                teams[name] = sq
        except Exception as e:  # noqa: BLE001 — one team failing shouldn't sink the rest
            log("[squads] %s failed (%r)" % (name, e))
    if not teams:
        log("[squads] nothing fetched — keeping existing cache")
        return 0
    out = {"fetched_at": datetime.now(timezone.utc).isoformat(), "teams": teams}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False, sort_keys=True)
    log("[squads] %d squads fetched" % len(teams))
    return len(teams)
