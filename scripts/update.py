#!/usr/bin/env python3
"""Update on command: refresh the live feed and rebuild the whole site.

This is the single entry point used by the daily GitHub Action and by anyone
who wants to update the site by hand:  python3 scripts/update.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wc import data, render  # noqa: E402

PUBLIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public")


def main():
    payload = data.refresh()
    files = render.render_site(payload)
    for relpath, content in files.items():
        out = os.path.join(PUBLIC, relpath)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(content)
    print(f"[update] refreshed data and wrote {len(files)} files to {PUBLIC}")


if __name__ == "__main__":
    main()
