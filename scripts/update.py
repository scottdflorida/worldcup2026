#!/usr/bin/env python3
"""Update on command: refresh the live feed and rebuild the whole site.

This is the single entry point used by the daily GitHub Action and by anyone
who wants to update the site by hand:  python3 scripts/update.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wc import blurbs, data, render  # noqa: E402

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


def main():
    payload = data.refresh()
    _refresh_blurbs(payload)        # update data/blurbs.json before rendering
    n = render.write_site(PUBLIC, payload)
    print(f"[update] refreshed data and wrote {n} files to {PUBLIC}")


if __name__ == "__main__":
    main()
