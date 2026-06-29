#!/usr/bin/env python3
"""Generate the per-team "road to the final" blurbs with Claude Sonnet.

  python3 scripts/blurbs.py USA              # one team (prints the result)
  python3 scripts/blurbs.py USA Brazil       # several teams
  python3 scripts/blurbs.py --all            # every team, but only those whose
                                             #   facts changed since last run
  python3 scripts/blurbs.py --all --force    # every team, regenerate all
  python3 scripts/blurbs.py USA --dry-run    # just print the prompt, no API call
  python3 scripts/blurbs.py --stale          # only teams whose fingerprint moved
                                             #   (this is what the daily job runs)

Needs ANTHROPIC_API_KEY in the environment. Writes data/blurbs.json.
Add --live to refresh the feed first instead of using the cached data.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wc import blurbs, data, render  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLURBS_PATH = os.path.join(ROOT, blurbs.BLURBS_PATH)


def main(argv):
    flags = {a for a in argv if a.startswith("--")}
    teams_arg = [a for a in argv if not a.startswith("--")]
    dry_run = "--dry-run" in flags
    force = "--force" in flags

    payload = data.refresh() if "--live" in flags else data.load_cache()
    ctx = render.Context(payload)

    if teams_arg:
        targets = teams_arg
    else:  # --all / --stale → every team
        targets = ctx.teams
    targets = [t for t in targets if t in ctx.teams]

    cache = blurbs.load_cache(BLURBS_PATH)

    if dry_run:
        for t in targets:
            brief = blurbs.team_brief(ctx, t)
            system, user = blurbs.build_messages(brief)
            print(f"\n===== {t}  (fingerprint {blurbs.fingerprint(brief)}) =====")
            print("--- SYSTEM ---\n" + system)
            print("\n--- USER ---\n" + user)
        return 0

    client = _client()
    changed = 0
    for t in targets:
        brief = blurbs.team_brief(ctx, t)
        fp = blurbs.fingerprint(brief)
        cached = cache.get(t)
        if not force and cached and cached.get("fingerprint") == fp:
            continue  # facts unchanged — keep the existing blurb
        text = blurbs.generate_blurb(client, brief)
        cache[t] = {"text": text, "fingerprint": fp}
        changed += 1
        print(f"\n● {t}\n{text}")

    blurbs.save_cache(cache, BLURBS_PATH)
    print(f"\n[blurbs] {changed} generated/updated, {len(cache)} cached → {BLURBS_PATH}")
    return 0


def _client():
    import anthropic
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        sys.exit("ANTHROPIC_API_KEY is not set — export it and re-run "
                 "(see scripts/blurbs.py header).")
    return anthropic.Anthropic()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
