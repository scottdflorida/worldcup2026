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

    files = render.render_site(payload)
    for relpath, content in files.items():
        out = os.path.join(PUBLIC, relpath)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(content)
    print(f"[build] wrote {len(files)} files to {PUBLIC}")


if __name__ == "__main__":
    main()
