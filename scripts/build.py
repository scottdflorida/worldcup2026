#!/usr/bin/env python3
"""Render the static site into public/ from cached (or freshly fetched) data.

Usage:
  python3 scripts/build.py            # build from the cached feed
  python3 scripts/build.py --fetch    # refresh the feed first, then build
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wc import config, data, render  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC = os.path.join(ROOT, "public")


def main():
    # Optional env overrides let tests rebuild synthetic tournament-state feeds
    # into a temp dir WITHOUT touching the committed real-data site. They default
    # to the real paths, so an unset build is byte-identical to the committed one.
    cache_path = os.environ.get("WC_DATA", config.CACHE_PATH)
    out_dir = os.environ.get("WC_OUT", PUBLIC)

    if "--fetch" in sys.argv:
        payload = data.refresh(cache_path=cache_path)
    else:
        payload = data.load_cache(cache_path=cache_path)

    n = render.write_site(out_dir, payload)
    print(f"[build] wrote {n} files to {out_dir}")


if __name__ == "__main__":
    main()
