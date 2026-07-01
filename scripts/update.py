#!/usr/bin/env python3
"""Update on command: refresh the live feed and rebuild the whole site.

This is the single entry point used by the daily GitHub Action and by anyone
who wants to update the site by hand:  python3 scripts/update.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wc import blurbs, data, kalshi, odds, render, squads, standings  # noqa: E402

PUBLIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public")


def _refresh_blurbs(payload):
    """Regenerate the road-to-final blurbs whose situation changed. Best-effort:
    only runs when an API key is configured, and never blocks the site build."""
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        print("[update] no ANTHROPIC_API_KEY — skipping blurb refresh")
        return
    try:
        ctx = render.Context(payload)
        n = blurbs.refresh_stale(ctx)
        print(f"[update] {n} blurbs regenerated")
    except Exception as e:  # noqa: BLE001 — never let blurb gen break the deploy
        print(f"[update] blurb refresh failed ({e!r}); building with existing blurbs")


def _refresh_blurbs_pt():
    """Translate into pt-BR the blurbs that just changed (keyed by the English
    fingerprint), for the site's EN/pt-BR toggle. Best-effort, same as the English
    pass: needs an API key, and never blocks the build. Runs after _refresh_blurbs."""
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return
    try:
        n = blurbs.refresh_pt()
        print(f"[update] {n} blurbs translated to pt-BR")
    except Exception as e:  # noqa: BLE001 — never let translation break the deploy
        print(f"[update] pt-BR blurb translation failed ({e!r}); keeping existing pt blurbs")


def _refresh_odds(payload):
    """Pull public match odds into data/odds.json — only on the daily 6am-PT run
    (REFRESH_ODDS=1), so the line moves once a day. Best-effort: no key or any
    failure just keeps the existing/model odds."""
    if os.environ.get("REFRESH_ODDS") != "1":
        return
    try:
        odds.refresh(force=True)
    except Exception as e:  # noqa: BLE001 — never let odds break the deploy
        print(f"[update] odds refresh failed ({e!r}); using existing odds")
    try:
        from wc import standings as _standings
        teams = sorted({row["team"]
                        for i in _standings.all_groups(payload["matches"]).values()
                        for row in i["table"]})
        kalshi.refresh(force=True, known_teams=teams)
    except Exception as e:  # noqa: BLE001 — never let Kalshi break the deploy
        print(f"[update] Kalshi odds refresh failed ({e!r}); using existing odds")


def _refresh_squads(payload):
    """Pull team squads from ESPN into data/squads.json — only on the daily run
    (REFRESH_ODDS=1), since rosters barely change. Best-effort: any failure keeps
    the existing cache."""
    if os.environ.get("REFRESH_ODDS") != "1":
        return
    try:
        teams = sorted({row["team"]
                        for i in standings.all_groups(payload["matches"]).values()
                        for row in i["table"]})
        squads.refresh(teams, force=True)
    except Exception as e:  # noqa: BLE001 — never let squads break the deploy
        print(f"[update] squad refresh failed ({e!r}); using existing squads")


def main():
    payload = data.refresh()
    _refresh_blurbs(payload)        # update data/blurbs.json before rendering
    _refresh_blurbs_pt()            # translate changed blurbs into data/blurbs.pt.json
    _refresh_odds(payload)          # update data/odds.json before rendering (Odds API + Kalshi)
    _refresh_squads(payload)        # update data/squads.json before rendering
    n = render.write_site(PUBLIC, payload)
    print(f"[update] refreshed data and wrote {n} files to {PUBLIC}")


if __name__ == "__main__":
    main()
