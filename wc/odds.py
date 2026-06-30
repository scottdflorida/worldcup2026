"""Public match odds from The Odds API, folded into 2-way "wins the tie" prices.

Knockout ties can't end level, but the public h2h market is 1X2 (home/draw/away),
so for each fixture we take the consensus (median across books) decimal price per
outcome, strip the bookmaker margin, split the draw evenly between the two sides
(extra time + penalties are ~a coin flip), and re-quote as two decimal odds with a
light house margin. Cached in data/odds.json and refreshed at most every TTL_HOURS
so the daily build stays well inside the free API quota.

render.betting_data reads the cache; teams without a public price fall back to the
group-form model odds. No key configured → the cache is just left as-is.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from statistics import median

SPORT = "soccer_fifa_world_cup"
ODDS_PATH = "data/odds.json"
TTL_HOURS = 8
MARGIN = 0.96  # house edge baked back in after de-vigging


def _key():
    return os.environ.get("ODDS_API_KEY")


def fetch_h2h(key):
    url = "https://api.the-odds-api.com/v4/sports/%s/odds/?%s" % (
        SPORT, urllib.parse.urlencode(
            {"apiKey": key, "regions": "us", "markets": "h2h", "oddsFormat": "decimal"}))
    with urllib.request.urlopen(url, timeout=25) as r:
        return json.loads(r.read().decode("utf-8"))


def _consensus(fixture):
    """Median decimal price per outcome name across all books."""
    buckets = {}
    for bk in fixture.get("bookmakers", []):
        for mk in bk.get("markets", []):
            if mk.get("key") != "h2h":
                continue
            for o in mk.get("outcomes", []):
                if o.get("price"):
                    buckets.setdefault(o["name"], []).append(float(o["price"]))
    return {name: median(v) for name, v in buckets.items() if v}


def _two_way(cons, home, away):
    if home not in cons or away not in cons:
        return None
    ph, pa = 1.0 / cons[home], 1.0 / cons[away]
    pd = 1.0 / cons.get("Draw", 1e9)
    s = ph + pa + pd
    if s <= 0:
        return None
    ph, pa, pd = ph / s, pa / s, pd / s          # de-vig
    Ph, Pa = ph + pd / 2.0, pa + pd / 2.0         # draw -> ET/pens, split evenly
    return (round(max(1.05, (1.0 / Ph) * MARGIN), 2),
            round(max(1.05, (1.0 / Pa) * MARGIN), 2))


def build_pairs(fixtures):
    pairs = {}
    for g in fixtures:
        home, away = g.get("home_team"), g.get("away_team")
        if not (home and away):
            continue
        tw = _two_way(_consensus(g), home, away)
        if not tw:
            continue
        pairs["|".join(sorted([home, away]))] = {home: tw[0], away: tw[1]}
    return pairs


def load_cache(path=ODDS_PATH):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def pair_odds(cache, team1, team2):
    """(odds1, odds2) for this matchup from the public cache, or None."""
    p = (cache or {}).get("pairs", {}).get("|".join(sorted([team1, team2])))
    if p and team1 in p and team2 in p:
        return p[team1], p[team2]
    return None


def refresh(path=ODDS_PATH, *, force=False, log=print):
    """Refetch if the cache is missing/stale; returns the number of priced ties."""
    key = _key()
    if not key:
        log("[odds] no ODDS_API_KEY — keeping existing odds")
        return 0
    cur = load_cache(path)
    if not force and cur.get("fetched_at"):
        try:
            age = (datetime.now(timezone.utc)
                   - datetime.fromisoformat(cur["fetched_at"])).total_seconds()
            if age < TTL_HOURS * 3600:
                log("[odds] cache fresh (%dh old) — skipping" % (age // 3600))
                return 0
        except ValueError:
            pass
    pairs = build_pairs(fetch_h2h(key))
    out = {"fetched_at": datetime.now(timezone.utc).isoformat(), "pairs": pairs}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False, sort_keys=True)
    log("[odds] %d ties priced from public market" % len(pairs))
    return len(pairs)
