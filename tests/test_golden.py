"""Golden build tests: rebuild each tournament snapshot and hash the output tree.

Every fixture state is rebuilt through scripts/build.py (pinned via WC_DATA_DIR /
WC_TODAY / WC_OUT) and the resulting {relpath: sha256} tree is compared to the
committed manifest tests/golden/<state>.json. This locks the entire rendered site
byte-for-byte, so any refactor that changes even one character of output is caught.

The manifests under tests/golden/*.json ARE committed — they are the reviewed,
version-controlled truth, so a fresh checkout passes with no setup. Regenerating
them (`python3 tests/regen_golden.py`) is an explicit "accept a new output
baseline" action: inspect the manifest diff in review, don't run it as a routine
post-refactor step. The full reference trees it also writes are gitignored,
local-only aids for unified diffs on failure.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from golden_harness import (  # noqa: E402
    STATES, build_site, hash_tree, manifest_path, reference_dir,
)

_MAX_DIFF_FILES = 3
_MAX_DIFF_LINES = 40


def _diff_excerpt(state, rel, cur_path):
    """A short unified diff between the golden reference copy and the fresh build."""
    ref_path = os.path.join(reference_dir(state), rel)
    if not os.path.exists(ref_path):
        return f"    (no reference copy for {rel}; run tests/regen_golden.py to enable diffs)"
    import difflib
    with open(ref_path, encoding="utf-8", errors="replace") as fh:
        ref_lines = fh.read().splitlines()
    with open(cur_path, encoding="utf-8", errors="replace") as fh:
        cur_lines = fh.read().splitlines()
    ud = difflib.unified_diff(
        ref_lines, cur_lines,
        fromfile=f"golden/{rel}", tofile=f"built/{rel}", lineterm="",
    )
    lines = []
    for i, line in enumerate(ud):
        if i >= _MAX_DIFF_LINES:
            lines.append("    ... (diff truncated)")
            break
        lines.append("    " + line)
    return "\n".join(lines)


class GoldenBuildTest(unittest.TestCase):
    pass


def _make_case(state):
    def test(self):
        mpath = manifest_path(state)
        if not os.path.exists(mpath):
            self.fail("golden manifest missing — run python3 tests/regen_golden.py")
        with open(mpath, encoding="utf-8") as fh:
            expected = json.load(fh)

        with tempfile.TemporaryDirectory() as out_dir:
            build_site(state, out_dir)
            actual = hash_tree(out_dir)
            if actual == expected:
                return

            exp_keys, act_keys = set(expected), set(actual)
            missing = sorted(exp_keys - act_keys)
            extra = sorted(act_keys - exp_keys)
            changed = sorted(k for k in exp_keys & act_keys if expected[k] != actual[k])

            report = [f"golden mismatch for state '{state}':"]
            if missing:
                report.append(f"  missing ({len(missing)}) in build: " + ", ".join(missing))
            if extra:
                report.append(f"  extra ({len(extra)}) in build: " + ", ".join(extra))
            if changed:
                report.append(f"  changed ({len(changed)}): " + ", ".join(changed[:20]))
            for rel in changed[:_MAX_DIFF_FILES]:
                report.append(_diff_excerpt(state, rel, os.path.join(out_dir, rel)))
            self.fail("\n".join(report))

    test.__name__ = "test_golden_" + state.replace("-", "_")
    return test


for _state in STATES:
    _case = _make_case(_state)
    setattr(GoldenBuildTest, _case.__name__, _case)


if __name__ == "__main__":
    unittest.main()
