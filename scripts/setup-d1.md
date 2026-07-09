# Betting pool: one-time D1 setup

The `/bets` page and its API (`functions/api/bets/*`) ship with the site, but
the pool stays in a "not set up yet" state until a **Cloudflare D1** database
exists and is bound as `DB` on the Pages project. This is infra, not code —
do it once from your machine.

## 1. Create the database

```sh
npx wrangler d1 create wc26-bets
```

This prints a `database_id`. Copy it into `wrangler.toml`:

```toml
[[d1_databases]]
binding = "DB"
database_name = "wc26-bets"
database_id = "the-id-you-just-got"
```

## 2. Apply the schema

```sh
npx wrangler d1 execute wc26-bets --remote --file=schema.sql
```

Creates `pools`, `players`, and `bets` (see `schema.sql` for the exact
columns). Safe to re-run — every statement is `CREATE TABLE IF NOT EXISTS` /
`CREATE INDEX IF NOT EXISTS`.

## 3. Bind it in the Pages project

The `[[d1_databases]]` block in `wrangler.toml` is only read by the local CLI
(`wrangler pages dev`, `wrangler d1 ...`). The deployed Pages project needs
its own binding, set in the dashboard:

Cloudflare dashboard → **Workers & Pages** → the `worldcup2026` Pages project
→ **Settings → Functions → D1 database bindings** → **Add binding**:

- Variable name: `DB`
- D1 database: `wc26-bets`

Add it for **Production** (and **Preview** too, if you want bets to work on
preview deploys). Then redeploy — push any commit, or **Retry deployment** on
the latest one — so the binding takes effect.

## 4. Local dev

```sh
npx wrangler pages dev public
```

Serves `public/` plus `functions/` locally, reading the `[[d1_databases]]`
binding from `wrangler.toml` so `/api/bets/*` works against the real
`wc26-bets` database (add `--d1 DB=<database_id> --local` instead if you'd
rather point at a local SQLite copy for throwaway testing).

Remember `public/` is generated — run `python3 scripts/build.py` first if
you've changed anything under `wc/`.

## Not runtime secrets

`ODDS_API_KEY` and `ANTHROPIC_API_KEY` are **GitHub Actions secrets**, read
by `.github/workflows/update.yml` at build time (they feed `wc/odds.py` and
the blurb generator). They are not Pages environment variables and D1 has
nothing to do with them — the daily Action commits their output
(`data/odds.json`, `public/bets-data.json`, etc.) straight into the repo, so
the deployed site never needs them at request time.
