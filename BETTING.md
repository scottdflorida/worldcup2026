# Betting pool — one-time setup

The `/bets` page and its API (`functions/api/bets/*`) are deployed, but the pool
stays in a "not set up yet" state until a **Cloudflare D1** database is created
and bound as `DB`. No external odds key is needed — odds are model-derived from
group-stage form and published in `public/bets-data.json` on every build.

## Steps (once)

1. **Create the database**

   ```sh
   npx wrangler d1 create wc-bets
   ```

2. **Create the tables**

   ```sh
   npx wrangler d1 execute wc-bets --remote --file=./schema.sql
   ```

3. **Bind it to the Pages project** — Cloudflare dashboard → your Pages project →
   **Settings → Functions → D1 database bindings** → Add:
   - Variable name: `DB`
   - D1 database: `wc-bets`

   Add it for **Production** (and Preview if you want bets on preview URLs).

4. **Redeploy** (push any commit, or "Retry deployment") so the binding takes effect.

That's it. Visit `/bets`, pick a name + a pool code, share the code with friends,
and you each start with $100.

## How it works

- **Identity** is lightweight: joining sets a private `wc_bet` cookie token. No
  passwords — fine for a friends pool.
- **Odds** are snapshotted onto each bet when placed, so later odds moves don't
  change a standing wager.
- **Settlement** is automatic: whenever anyone loads the pool, every open bet on a
  now-decided match is settled (win → `stake × odds` credited; loss → stake gone).
  Results come from `bets-data.json`, which the daily update job republishes.
- **$0 = out** (you can't stake more than your balance), and you can bet any
  amount, any number of times, on any open match.

To swap the model odds for real public bookmaker odds later, fetch them in the
update job and write `odds1`/`odds2` into `bets-data.json` instead of the model
values — the backend doesn't care where the numbers come from.
