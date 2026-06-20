# World Cup 2026 Tracker → worldcup.sflorida.studio

A self-updating static site that tracks the 2026 FIFA World Cup. Pick **any
team (or teams)** and see their live group situation, their projected **road to
the final**, and **who they could face** at each knockout round based on the
current standings — plus full group tables and the complete bracket.

- **Live data:** [`openfootball/worldcup.json`](https://github.com/openfootball/worldcup.json) — public domain, no API key, updated from official results.
- **Hosting:** Cloudflare Pages (Git integration) on `worldcup.sflorida.studio`.
- **Auto-update:** a GitHub Action refreshes the data and rebuilds the site once a day; Pages redeploys on the push.

---

## How it works

```
wc/            the engine (pure Python, standard library only)
  config.py    data source, tournament meta, default watchlist, team colors
  data.py      fetch / cache / load the live feed
  standings.py group tables, FIFA tiebreakers, clinch/elimination detection
  bracket.py   resolve bracket slots (1C, 2F, 3A/B/C/D/F, W76…) + path projection
  render.py    build the multi-page static site
  flags.py / util.py   emoji flags, slugs, per-team accent colors
scripts/
  fetch.py     refresh the cached feed only
  build.py     render public/ from the cache  (--fetch to refresh first)
  update.py    refresh data AND rebuild  ← the "update on command" entry point
data/          cached copy of the live feed (committed so builds are reproducible)
public/        the generated site that Cloudflare Pages serves
.github/workflows/update.yml   the daily refresh job
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

After that, every push (including the daily Action) auto-deploys.

> Prefer Cloudflare to build instead of serving the committed output? Set the
> build command to `python3 scripts/build.py` — Python is available in the Pages
> build image.

## Daily auto-update

`.github/workflows/update.yml` runs at **12:00 UTC daily** (and on demand from
the Actions tab). It runs `scripts/update.py`, commits any changes, and pushes —
which triggers the Cloudflare deploy. No secrets required.

## Customize

- **Default watchlist** (teams pinned on a first visit): `DEFAULT_WATCH` in `wc/config.py`.
- **Team colors:** add entries to `TEAM_META` in `wc/config.py` (everyone else gets an auto color).
- **Look & feel:** the `STYLE` block in `wc/render.py`.
- **Data source:** `DATA_URL` in `wc/config.py`.
