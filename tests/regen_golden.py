#!/usr/bin/env python3
"""Regenerate the golden hash manifests (and diff-reference build trees).

    python3 tests/regen_golden.py            # all states
    python3 tests/regen_golden.py current    # a subset

For each state it builds the fixture snapshot and writes:
    tests/golden/<state>.json   -> {relpath: sha256} manifest — COMMITTED, the
                                   reviewed pass/fail truth
    tests/golden/<state>/       -> the full rendered site — gitignored, local-only,
                                   so test_golden can show a unified diff on mismatch

Running this is an explicit "accept a new output baseline" action, only for
INTENTIONAL output changes: it overwrites the committed manifests with whatever
the current code emits, so the manifest diff must be inspected in code review.
It is NOT a routine post-refactor step — a behavior-preserving refactor should
leave every manifest untouched.
"""
from __future__ import annotations

import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from golden_harness import (  # noqa: E402
    GOLDEN_DIR, STATES, build_site, hash_tree, manifest_path, reference_dir,
)


def regen(states):
    os.makedirs(GOLDEN_DIR, exist_ok=True)
    for state in states:
        ref = reference_dir(state)
        if os.path.isdir(ref):
            shutil.rmtree(ref)
        os.makedirs(ref)
        build_site(state, ref)
        manifest = hash_tree(ref)
        with open(manifest_path(state), "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print(f"[regen] {state}: {len(manifest)} files -> {os.path.basename(manifest_path(state))}")


if __name__ == "__main__":
    wanted = sys.argv[1:] or STATES
    unknown = [s for s in wanted if s not in STATES]
    if unknown:
        sys.exit(f"unknown state(s): {', '.join(unknown)}; known: {', '.join(STATES)}")
    regen(wanted)
