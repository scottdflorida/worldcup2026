"""Fetch and load the World Cup 2026 match feed."""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timezone

from . import config


def fetch(url: str = config.DATA_URL, timeout: int = 30) -> dict:
    """Download the live feed. Raises on network/HTTP error."""
    req = urllib.request.Request(url, headers={"User-Agent": "worldcup-sflorida-studio/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def save_cache(payload: dict, cache_path: str = config.CACHE_PATH) -> None:
    os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    with open(config.LAST_UPDATED_PATH, "w", encoding="utf-8") as fh:
        fh.write(datetime.now(timezone.utc).isoformat())


def load_cache(cache_path: str = config.CACHE_PATH) -> dict:
    with open(cache_path, encoding="utf-8") as fh:
        return json.load(fh)


def refresh(cache_path: str = config.CACHE_PATH) -> dict:
    """Fetch live data; only rewrite the cache + timestamp if results changed.

    Keeping the timestamp stable when nothing changed is what makes the frequent
    polls idempotent: identical data -> identical generated site -> no git diff ->
    no commit -> no Cloudflare deploy. So the site only republishes when a match
    result actually moves, staying well under Cloudflare's monthly deploy cap.
    """
    try:
        payload = fetch()
    except Exception as exc:  # noqa: BLE001 - network is best-effort
        print(f"[data] live fetch failed ({exc}); using cached copy")
        return load_cache(cache_path)
    try:
        existing = load_cache(cache_path)
    except (FileNotFoundError, ValueError):
        existing = None
    if existing == payload:
        print("[data] no change since last fetch")
        return payload
    save_cache(payload, cache_path)
    label = "first cache" if existing is None else "results changed"
    print(f"[data] {label}; cached {len(payload.get('matches', []))} matches")
    return payload


def changed_since_cache(cache_path: str = config.CACHE_PATH) -> bool:
    """True if a live fetch would differ from the cached copy (best-effort)."""
    try:
        return fetch() != load_cache(cache_path)
    except Exception:  # noqa: BLE001
        return False


def last_updated() -> str | None:
    try:
        with open(config.LAST_UPDATED_PATH, encoding="utf-8") as fh:
            return fh.read().strip()
    except FileNotFoundError:
        return None


# --- match helpers -------------------------------------------------------

def has_result(match: dict) -> bool:
    score = match.get("score") or {}
    return bool(score.get("ft"))


def final_score(match: dict):
    """Return (goals1, goals2) using full-time + (if present) extra time."""
    score = match.get("score") or {}
    ft = score.get("ft")
    if not ft:
        return None
    g1, g2 = ft[0], ft[1]
    et = score.get("et")
    if et:  # extra time supersedes the 90-minute score
        g1, g2 = et[0], et[1]
    return g1, g2


def penalty_winner(match: dict):
    """For knockout draws decided on penalties, return the winning team name."""
    score = match.get("score") or {}
    pens = score.get("p")
    if not pens:
        return None
    return match["team1"] if pens[0] > pens[1] else match["team2"]
