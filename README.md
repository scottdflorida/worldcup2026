# World Cup 2026 Tracker → worldcup.sflorida.studio

A self-updating static site that tracks the 2026 FIFA World Cup. Pick **any
team (or teams)** and see their live group situation, their projected **road to
the final**, and **who they could face** at each knockout round based on the
current standings — plus full group tables and the complete bracket.

- **Live data:** [`openfootball/worldcup.json`](https://github.com/openfootball/worldcup.json) — public domain, no API key, updated from official results.
- **Hosting:** Cloudflare Pages (Git integration) on `worldcup.sflorida.studio`.
- **Auto-update:** a GitHub Action polls every 5 min during the daily match window and rebuilds the site; Pages redeploys whenever a result actually changed something (see **Updates: end-of-match**, below).

---

## How it works

```
wc/            the engine (pure Python, standard library only)
  config.py    data source, tournament meta, default watchlist, team colors
  data.py      fetch / cache / load the live feed
  standings.py group tables, FIFA tiebreakers, clinch/elimination detection
  bracket.py   resolve bracket slots (1C, 2F, 3A/B/C/D/F, W76…) + path projection
  times.py     kickoff time formatting / timezone handling
  components.py  reusable HTML fragment builders shared across pages
  shell.py     the page shell (head, nav, footer) every page renders into
  render.py    orchestrates the multi-page static build
  pages/       one module per page family (home, group, team, bracket, calendar, bets, …)
  assets/      style.css, app.js, and the original SVGs, copied into public/ as-is
  blurbs.py    AI-written "road to the final" blurbs (Anthropic API, cached + fingerprinted)
  i18n.py      client-side EN / pt-BR toggle (dict + regex rules + DOM walk + MutationObserver)
  odds.py      public match odds (The Odds API), folded into 2-way prices; model-derived fallback
  squads.py    squad/roster data
  flags.py / util.py   emoji flags, slugs, per-team accent colors
scripts/
  fetch.py       refresh the cached feed only
  build.py       render public/ from the cache  (--fetch to refresh first)
  update.py      refresh data AND rebuild  ← the daily entry point
  blurbs.py      regenerate road-to-final blurbs standalone
  setup-d1.md    one-time Cloudflare D1 setup for the betting pool
data/          cached copy of the live feed + odds cache (committed so builds are reproducible)
public/        the generated site that Cloudflare Pages serves
functions/     Cloudflare Pages Functions
  api/live.js        live in-match scores (proxies ESPN)
  api/bets/*.js       the play-money betting pool API (Cloudflare D1-backed)
tests/         golden fixtures for five tournament states + unit tests (see Tests, below)
.github/workflows/
  update.yml   polls the live feed and rebuilds; commits only when results change
  ci.yml       runs the test suite on every push to main and every PR
wrangler.toml  local Cloudflare config (Pages build output + D1 binding) — see scripts/setup-d1.md
```

The bracket and projections are **fully data-driven**: the feed encodes knockout
participants as slots (`2C` = Group C runner-up, `3A/B/C/D/F` = a third-placed
team, `W76` = winner of match 76). As results land, those slots resolve to real
teams automatically — no hand-editing.

## Update the site on command

```bash
python3 scripts/update.py     # pull the latest results and rebuild everything
```

Or just rebuild from the cached data (no network):

```bash
python3 scripts/build.py
```

## Preview locally

```bash
python3 scripts/build.py
python3 -m http.server 8765 --directory public
# open http://localhost:8765
```

## Deploy to Cloudflare Pages (one-time, in the dashboard)

1. Create a GitHub repo and push this project.
2. Cloudflare dashboard → **Workers & Pages → Create → Pages → Connect to Git**, and select the repo.
3. Build settings:
   - **Framework preset:** None
   - **Build command:** *(leave empty)* — the site is pre-built and committed to `public/`
   - **Build output directory:** `public`
4. **Save and Deploy.**
5. In the new Pages project → **Custom domains → Set up a domain →** `worldcup.sflorida.studio` (one click, since `sflorida.studio` is already on Cloudflare).

After that, every push (including the update Action) auto-deploys. The
`functions/` directory is picked up automatically — `/api/live` (live
in-match scores) works with no extra config. `/api/bets/*` (the betting pool)
also deploys automatically, but stays in a "not set up yet" state until a D1
database is created and bound — see **Local backend (betting)** below.

> Prefer Cloudflare to build instead of serving the committed output? Set the
> build command to `python3 scripts/build.py` — Python is available in the Pages
> build image.

## Updates: end-of-match

`.github/workflows/update.yml` polls the live feed **every 5 min during the
daily match window** (14:00–07:59 UTC, to cover late knockouts that run to
extra time/penalties), plus a daily safety run and a daily betting-odds
refresh. It rebuilds the site but **commits only when results actually
changed** (`scripts/update.py` keeps the timestamp stable when nothing moved,
so an unchanged poll regenerates byte-identical files and produces no
commit). Net effect: the site republishes within ~5 min of a result landing
in the feed, and **each real result is exactly one Cloudflare deploy** —
staying far under the free tier's 500 deploys/month. (Latency is bounded by
the openfootball feed, which posts results a few minutes after full-time.)

You can also update from your machine any time with `python3 scripts/update.py`,
or from the **Actions tab → Update site → Run workflow** (which also accepts a
"refresh betting odds" input, for pulling fresh prices from The Odds API
outside the daily schedule).

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Runs on every push/PR via `.github/workflows/ci.yml` (stdlib only — no pip
install, same zero-dependency story as the rest of the project).

Two kinds of coverage live under `tests/`:

- **Golden fixtures** — five real tournament snapshots lifted from this repo's
  own git history (early groups, the thirds race, groups complete, mid-knockout
  with penalty shootouts, and the current state) get rebuilt and hash-compared
  against committed manifests, so a change that silently alters standings math,
  bracket resolution, or rendered HTML for *any* tournament state gets caught,
  not just today's real state.
- **Unit tests** for the pure-logic modules (tiebreakers, slot resolution,
  time formatting, etc).

Three env-var seams make this possible without ever touching the committed
real-data site:

- `WC_DATA_DIR` — point at a fixture feed instead of the real cached one.
- `WC_TODAY` — pin "today" so clinch/elimination status and calendar
  rendering are deterministic regardless of when the test runs.
- `WC_OUT` — render into a scratch directory instead of `public/`.

All three default to the real paths/clock, so an unset build (`python3
scripts/build.py`) is byte-identical to the committed site.

## Local backend (betting)

The `/bets` pool needs a Cloudflare D1 database bound as `DB`. See
[`wrangler.toml`](wrangler.toml) for the local config and
[`scripts/setup-d1.md`](scripts/setup-d1.md) for the one-time setup (create
the database, apply `schema.sql`, bind it in the Pages project) and for
running `wrangler pages dev` locally. Details on how the pool itself works —
identity, odds, settlement — are in [`BETTING.md`](BETTING.md).

## Customize

- **Default watchlist** (teams pinned on a first visit): `DEFAULT_WATCH` in `wc/config.py`.
- **Team colors:** add entries to `TEAM_META` in `wc/config.py` (everyone else gets an auto color).
- **Look & feel:** `wc/assets/style.css`.
- **Data source:** `DATA_URL` in `wc/config.py`.
