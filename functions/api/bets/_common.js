// Shared helpers for the play-money betting endpoints (Cloudflare Pages Functions
// backed by a D1 database bound as `DB`). Files prefixed with _ are not routes.

export function json(obj, status, headers) {
  return new Response(JSON.stringify(obj), {
    status: status || 200,
    // no-store: these are per-player, balance-bearing replies — never let a CDN or
    // browser cache serve one player's pool state (or a stale balance) to anyone.
    headers: Object.assign(
      { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
      headers || {}),
  });
}

export function round2(n) {
  return Math.round((Number(n) || 0) * 100) / 100;
}

export function getCookie(request, name) {
  const c = request.headers.get("Cookie") || "";
  const m = c.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
  return m ? decodeURIComponent(m[1]) : null;
}

export function newToken() {
  const a = new Uint8Array(18);
  crypto.getRandomValues(a);
  return Array.from(a).map((b) => b.toString(16).padStart(2, "0")).join("");
}

// A long-lived first-party cookie mirroring the active membership token, so
// identity survives a localStorage wipe on the SAME device: getPlayer reads it
// as a fallback, and the client restores the membership from the state reply.
// HttpOnly (server-only) + Secure; SameSite=Lax is fine for same-site fetches.
export function tokenCookie(token) {
  return `wc_bet=${token}; Path=/; Max-Age=34560000; HttpOnly; Secure; SameSite=Lax`;
}

// The knockout matches + model odds + results, published by the static build.
export async function loadData(request) {
  try {
    const url = new URL("/bets-data.json", request.url).toString();
    const r = await fetch(url, { cf: { cacheTtl: 60, cacheEverything: true } });
    if (r.ok) return await r.json();
  } catch (e) { /* fall through */ }
  return { matches: [], flags: {} };
}

export async function getPlayer(env, request) {
  // active membership token from the client; legacy cookie is a one-time fallback
  const t = request.headers.get("X-Bet-Token") || getCookie(request, "wc_bet");
  if (!t) return null;
  return await env.DB.prepare("SELECT * FROM players WHERE token=?").bind(t).first();
}

// Settle every still-open bet whose match now has a result. Stake was already
// taken at placement, so a win just credits stake*odds back; a loss does nothing.
//
// IDEMPOTENT + ATOMIC. This runs on EVERY request from EVERY pool member, so
// concurrent callers routinely try to settle the same bets at once. The fix is
// per-decided-match, three statements inside ONE db.batch() (an atomic, all-or-
// nothing transaction):
//   1. credit each winner's balance by the SUM of their winning bets' payouts,
//      read from bets that are STILL 'open' at this point in the batch;
//   2. flip those winning bets 'open' -> 'won' (guarded on status='open');
//   3. flip the losing bets 'open' -> 'lost'.
// Ordering is load-bearing: statement 1 must read the payouts BEFORE statement 2
// changes their status. Because all three commit together, there is no window in
// which a winner is credited-but-unclaimed or claimed-but-uncredited — a crash
// rolls the whole transaction back. And it is idempotent: a second (concurrent or
// later) settle finds the bets already 'won', so statement 1 sums 0 open payouts
// and updates 0 players, and statement 2 updates 0 rows. Winners are paid exactly
// once. SQLite serializes write transactions, so two racing batches can't
// interleave: one commits fully, the other then sees no open bets and no-ops.
// The credit uses the same ROUND(stake*odds,2) expression stored as `payout`, so
// balance and payout can never drift apart.
export async function settleAll(env, data) {
  const decided = {};
  (data.matches || []).forEach((m) => { if (m.decided) decided[m.num] = m.winner; });
  if (!Object.keys(decided).length) return;
  const open = (await env.DB.prepare("SELECT DISTINCT match_num FROM bets WHERE status='open'").all()).results || [];
  const todo = open.map((r) => r.match_num).filter((n) => n in decided);
  if (!todo.length) return;
  const stmts = [];
  for (const num of todo) {
    const winner = decided[num];
    stmts.push(env.DB.prepare(
      "UPDATE players SET balance = balance + (" +
      "SELECT COALESCE(SUM(ROUND(stake*odds,2)),0) FROM bets " +
      "WHERE player_id=players.id AND status='open' AND match_num=? AND pick=?) " +
      "WHERE id IN (SELECT player_id FROM bets WHERE status='open' AND match_num=? AND pick=?)")
      .bind(num, winner, num, winner));
    stmts.push(env.DB.prepare(
      "UPDATE bets SET status='won', payout=ROUND(stake*odds,2) WHERE status='open' AND match_num=? AND pick=?")
      .bind(num, winner));
    stmts.push(env.DB.prepare(
      "UPDATE bets SET status='lost', payout=0 WHERE status='open' AND match_num=? AND pick<>?")
      .bind(num, winner));
  }
  if (stmts.length) await env.DB.batch(stmts);
}
