"""Kalshi prediction-market odds for FIFA World Cup knockout matches.

Fetches binary "will [team] win?" contracts, converts the mid-price
(yes_bid + yes_ask)/2 from cents to an implied probability, and re-quotes
as two-way decimal odds with a small house margin. Results are merged into
data/odds.json as additional pairs, overriding The Odds API price for any
matchup where Kalshi data is available.

Set KALSHI_API_KEY to enable live fetching. No key → cache is left as-is.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone

KALSHI_BASE = "https://api.kalshi.com/trade-api/v2"
ODDS_PATH = "data/odds.json"
KALSHI_PATH = "data/kalshi.json"
TTL_HOURS = 2
MARGIN = 0.96

# Kalshi series tickers to search for World Cup markets (tried in order)
_WC_SERIES = ["FIFAWC26", "FIFA26", "WORLDCUP26"]

# Kalshi sometimes uses different country names; map to our canonical names
_KALSHI_TO_CANONICAL = {
    "United States": "USA",
    "US": "USA",
    "Bosnia": "Bosnia & Herzegovina",
    "Congo": "DR Congo",
    "Republic of Ireland": "Ireland",
    "Ivory Coast": "Côte d'Ivoire",
}

# Reverse map for lookup: our canonical -> what Kalshi might call it
_CANONICAL_TO_KALSHI = {v: k for k, v in _KALSHI_TO_CANONICAL.items()}


def _key():
    return os.environ.get("KALSHI_API_KEY")


def _headers(key):
    return {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    }


def _fetch_series(key, series_ticker):
    """Fetch all open markets for one series ticker; returns [] on any error."""
    params = urllib.parse.urlencode({"series_ticker": series_ticker, "limit": 200, "status": "open"})
    url = f"{KALSHI_BASE}/markets?{params}"
    req = urllib.request.Request(url, headers=_headers(key))
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8")).get("markets", [])
    except Exception:
        return []


def fetch_markets(key):
    """Return all WC markets found across known series tickers."""
    for series in _WC_SERIES:
        markets = _fetch_series(key, series)
        if markets:
            return markets
    return []


def _mid_price(market):
    """Best-estimate yes probability in cents (0-100) from bid/ask or last."""
    bid = market.get("yes_bid") or 0
    ask = market.get("yes_ask") or 0
    if bid and ask:
        return (bid + ask) / 2.0
    return market.get("last_price") or bid or ask or None


def _canonical(name):
    """Convert a Kalshi team name to our canonical form."""
    return _KALSHI_TO_CANONICAL.get(name, name)


def _kalshi_name(name):
    """Convert our canonical team name to the Kalshi variant (if different)."""
    return _CANONICAL_TO_KALSHI.get(name, name)


def _extract_pair(market, known_teams):
    """
    Try to identify a market as a binary "team A wins their match" contract.

    Returns (team_a, yes_prob) if successful, else None.

    Looks for markets whose title contains exactly one known team name followed
    by "win" or "advance", which is Kalshi's typical format for a binary sport
    outcome: "Will [England] win their Round of 16 match?"
    """
    title = (market.get("title") or "") + " " + (market.get("subtitle") or "")
    title_lower = title.lower()

    if "win" not in title_lower and "advance" not in title_lower:
        return None

    yes_cents = _mid_price(market)
    if not yes_cents:
        return None
    yes_prob = yes_cents / 100.0
    if not (0.04 <= yes_prob <= 0.96):
        return None

    matched = [t for t in known_teams if _kalshi_name(t).lower() in title_lower
               or t.lower() in title_lower]
    if len(matched) != 1:
        return None

    return matched[0], yes_prob


def build_pairs(markets, known_teams):
    """
    Convert a list of Kalshi markets into a pair-odds dict.

    For each binary "team A wins" market we record team A's implied probability.
    When we later see the same match from team B's side, we cross-check. If we
    only ever see one side, we infer the opponent's probability as 1 - p(A).

    Returns {"|".join(sorted([t1, t2])): {t1: decimal_odds, t2: decimal_odds}}
    """
    # team -> {yes_prob, title} (latest / best price wins)
    team_win_prob: dict[str, float] = {}

    for m in markets:
        result = _extract_pair(m, known_teams)
        if result:
            team, prob = result
            team_win_prob[team] = prob

    # Group into pairs: look for matches where we know both sides or can infer
    # from the fixture schedule (pairs are determined externally and passed in as
    # known_pairs if available — here we infer from probability complement).
    pairs = {}
    seen = set()
    for team, prob_a in team_win_prob.items():
        if team in seen:
            continue
        # Try to find the opponent: another team whose win prob ≈ 1 - prob_a
        opponent = None
        best_gap = 0.10  # must be within 10 pp of the complement
        for other, prob_b in team_win_prob.items():
            if other == team or other in seen:
                continue
            gap = abs((prob_a + prob_b) - 1.0)
            if gap < best_gap:
                best_gap = gap
                opponent = other

        if opponent is None:
            continue

        prob_b = team_win_prob[opponent]
        total = prob_a + prob_b
        if total <= 0:
            continue
        # Normalize and apply margin
        p_a = prob_a / total
        p_b = prob_b / total
        o_a = round(max(1.05, (1.0 / p_a) * MARGIN), 2)
        o_b = round(max(1.05, (1.0 / p_b) * MARGIN), 2)

        key = "|".join(sorted([team, opponent]))
        pairs[key] = {team: o_a, opponent: o_b}
        seen.add(team)
        seen.add(opponent)

    return pairs


def load_cache(path=KALSHI_PATH):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def pair_odds(cache, team1, team2):
    """(odds1, odds2) from the Kalshi cache, or None."""
    p = (cache or {}).get("pairs", {}).get("|".join(sorted([team1, team2])))
    if p and team1 in p and team2 in p:
        return p[team1], p[team2]
    return None


def _merge_into_odds_json(kalshi_pairs, odds_path=ODDS_PATH):
    """Write kalshi_pairs into data/odds.json, overriding existing pairs."""
    try:
        with open(odds_path, encoding="utf-8") as f:
            existing = json.load(f)
    except (OSError, ValueError):
        existing = {}

    existing.setdefault("pairs", {}).update(kalshi_pairs)
    with open(odds_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=1, ensure_ascii=False, sort_keys=True)


def refresh(odds_path=ODDS_PATH, kalshi_path=KALSHI_PATH, *, force=False, log=print,
            known_teams=None):
    """Fetch Kalshi odds, cache in data/kalshi.json, merge into data/odds.json.

    known_teams: list of canonical team names currently in the tournament.
    Returns the number of pairs successfully priced.
    """
    key = _key()
    if not key:
        log("[kalshi] no KALSHI_API_KEY — keeping existing odds")
        return 0

    cur = load_cache(kalshi_path)
    if not force and cur.get("fetched_at"):
        try:
            age = (datetime.now(timezone.utc)
                   - datetime.fromisoformat(cur["fetched_at"])).total_seconds()
            if age < TTL_HOURS * 3600:
                log("[kalshi] cache fresh (%dh old) — skipping" % (age // 3600))
                return 0
        except ValueError:
            pass

    if known_teams is None:
        known_teams = []

    markets = fetch_markets(key)
    if not markets:
        log("[kalshi] no markets returned — keeping existing odds")
        return 0

    pairs = build_pairs(markets, known_teams)
    out = {"fetched_at": datetime.now(timezone.utc).isoformat(), "pairs": pairs}
    with open(kalshi_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False, sort_keys=True)

    _merge_into_odds_json(pairs, odds_path)
    log("[kalshi] %d pairs priced from Kalshi and merged into odds" % len(pairs))
    return len(pairs)
