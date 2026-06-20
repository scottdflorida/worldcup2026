#!/usr/bin/env python3
"""Render the static site into public/ from cached (or freshly fetched) data.

Usage:
  python3 scripts/build.py            # build from the cached feed
  python3 scripts/build.py --fetch    # refresh the feed first, then build
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wc import data, render  # noqa: E402

PUBLIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public")


def main():
    if "--fetch" in sys.argv:
        payload = data.refresh()
    else:
        payload = data.load_cache()

    n = render.write_site(PUBLIC, payload)
    print(f"[build] wrote {n} files to {PUBLIC}")


if __name__ == "__main__":
    main()
