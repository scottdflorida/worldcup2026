"""Shared plumbing for the golden site-build tests.

Both test_golden.py (compare against a committed hash manifest) and
regen_golden.py (write the manifests) drive the real build the same way: a
subprocess `scripts/build.py` invocation pointed at a fixture snapshot via the
three build seams --

    WC_DATA_DIR  every data file (feed + blurbs/odds/squads/last_updated) is read
                 from this directory instead of the repo's real data/
    WC_TODAY     pins the build's notion of "today" (Pacific) so the Matchday
                 Pulse window and the calendar today-cell are deterministic
    WC_OUT       writes the rendered site here instead of public/

Discovered relative to this file, so the suite works from any cwd and against
whatever repo root it is copied into.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(TESTS_DIR)
FIXTURES_DIR = os.path.join(TESTS_DIR, "fixtures")
GOLDEN_DIR = os.path.join(TESTS_DIR, "golden")

# Tournament snapshots, earliest to latest. Each has a directory under
# tests/fixtures/<state>/ holding the six data files + meta.json.
STATES = [
    "early-groups",     # matchday 1 done, no knockout slots resolved
    "thirds-race",      # late groups, best-third race live, some slots resolved
    "groups-complete",  # all 72 group games played, Round of 32 fully seeded
    "mid-knockout",     # R32 done, R16 partly done, incl. penalty shootouts
    "current",          # repo HEAD
]


def fixture_dir(state: str) -> str:
    return os.path.join(FIXTURES_DIR, state)


def today_for(state: str) -> str:
    with open(os.path.join(fixture_dir(state), "meta.json"), encoding="utf-8") as fh:
        return json.load(fh)["today"]


def manifest_path(state: str) -> str:
    return os.path.join(GOLDEN_DIR, state + ".json")


def reference_dir(state: str) -> str:
    """Where regen keeps a full copy of the golden build, for unified diffs."""
    return os.path.join(GOLDEN_DIR, state)


def build_site(state: str, out_dir: str) -> None:
    """Subprocess-build one fixture state into out_dir. Raises on build failure."""
    # Strip every ambient build seam (WC_*) and pipeline key so the golden build
    # is pinned to fixture inputs regardless of the caller's shell environment —
    # any future WC_* seam is neutralized by construction, not by enumeration.
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("WC_") and k not in ("ODDS_API_KEY", "ANTHROPIC_API_KEY")}
    env["WC_DATA_DIR"] = fixture_dir(state)
    env["WC_TODAY"] = today_for(state)
    env["WC_OUT"] = out_dir
    subprocess.run(
        [sys.executable, "scripts/build.py"],
        cwd=REPO_ROOT, env=env, check=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )


def hash_tree(root: str) -> dict:
    """{relpath: sha256hex} over every file under root (sorted, path-stable)."""
    out = {}
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            fp = os.path.join(dirpath, fn)
            rel = os.path.relpath(fp, root).replace(os.sep, "/")
            with open(fp, "rb") as fh:
                out[rel] = hashlib.sha256(fh.read()).hexdigest()
    return out
