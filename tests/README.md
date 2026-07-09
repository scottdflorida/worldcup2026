# Tests

Zero-dependency `unittest` suite for the World Cup 2026 static site generator.
Two layers:

1. **Unit tests** — pure-function behaviour of the render engine's building blocks.
2. **Golden build tests** — rebuild whole-tournament snapshots and lock the entire
   rendered site byte-for-byte against a hash manifest.

## Running

```sh
# from the repo root
python3 -m unittest discover -s tests            # everything
python3 -m unittest discover -s tests -v         # verbose
python3 -m unittest tests.test_bracket           # one module
```

Everything passes on a fresh checkout with no setup — the golden manifests are
committed alongside the tests.

## The build seams

Everything the suite does flows through three environment variables that
`scripts/build.py` and the `wc/` package honour. Unset, they default to the real
data and `public/`, so a normal build is unaffected.

| Var           | Meaning                                                                 |
|---------------|-------------------------------------------------------------------------|
| `WC_DATA_DIR` | Read every data file (feed + `blurbs`/`blurbs.pt`/`odds`/`squads`/`last_updated`) from this directory instead of `data/`. |
| `WC_TODAY`    | Pin the build's notion of "today" (Pacific, `YYYY-MM-DD`). Drives the Matchday Pulse window and the calendar today-cell. Unset ⇒ real clock. |
| `WC_OUT`      | Write the rendered site here instead of `public/`.                      |

(`WC_DATA` — a single-file feed override — still exists and takes precedence over
`WC_DATA_DIR` for the feed file only; the golden harness clears it so fixtures win.)

## Golden states

Each fixture under `tests/fixtures/<state>/` is a coherent snapshot lifted from
real git history: all six data files plus `meta.json` (`{"today": "..."}`, the PT
date of that commit). The five states span the tournament lifecycle:

| State             | Source sha | `today`     | What it exercises                                                        |
|-------------------|------------|-------------|--------------------------------------------------------------------------|
| `early-groups`    | `cb17a10`  | 2026-06-19  | Matchday 1 done (30/72 group games); no knockout slots resolved.         |
| `thirds-race`     | `2c71045`  | 2026-06-25  | Late groups (56/72); best-third race live; some group slots resolved.    |
| `groups-complete` | `af3cf09`  | 2026-06-28  | All 72 group games played; Round of 32 fully seeded; no knockout results.|
| `mid-knockout`    | `88d9082`  | 2026-07-07  | R32 complete, R16 partly played, incl. penalty shootouts (`score.p`); QFs still `W..`/`L..` tokens. |
| `current`         | `ca2d3ea`  | 2026-07-08  | Repo HEAD (R16 complete, QFs pending).                                    |

Files that post-date a feature in history (the `blurbs`/`odds`/`squads` caches
were added later) are stored as empty stubs (`{}`) in the earlier fixtures, and a
missing `last_updated.txt` is filled with the commit's UTC timestamp — so every
fixture is a complete, self-contained, deterministic input set.

## Accepting a new golden baseline

The manifests (`tests/golden/<state>.json`) **are committed** — they are the
reviewed, version-controlled truth the tests compare against. Regenerating them
is an explicit *accept-the-new-baseline* action reserved for **intentional**
output changes:

```sh
python3 tests/regen_golden.py            # all states
python3 tests/regen_golden.py current    # a subset
```

Then inspect the manifest diff in code review — it is the record of exactly which
pages changed. A behavior-preserving refactor should leave every manifest
untouched; if regen changes one, that's a finding, not a formality. Regen also
writes `tests/golden/<state>/` — a full copy of each rendered site, **gitignored
and local-only**, used by `test_golden.py` to print unified diffs on mismatch
(without it, failures still report exactly which files changed).

`test_golden.py` rebuilds each state into a temp dir, hashes the tree, and compares
to the manifest. On mismatch it reports missing/extra files and a short unified
diff for the first few changed files (when a local reference tree exists).

## Layout

```
tests/
  README.md
  __init__.py
  golden_harness.py     # shared build/hash plumbing (not a test module)
  regen_golden.py       # writes the manifests + reference trees
  test_golden.py        # rebuild-and-compare, one test per state
  test_bracket.py       # slot-token resolution, match_winner/loser, shootouts
  test_standings.py     # FIFA tiebreakers (head-to-head, GD), best-thirds shape
  test_data.py          # has_result / final_score / penalty_winner
  test_util.py          # slug / page_for / deterministic accents
  fixtures/<state>/     # six data files + meta.json per state
  golden/<state>.json   # committed hash manifests — the pass/fail truth
  golden/<state>/       # local-only reference trees from regen (gitignored)
```
