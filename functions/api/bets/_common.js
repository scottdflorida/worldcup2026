// Shared helpers for the play-money betting endpoints (Cloudflare Pages Functions
// backed by a D1 database bound as `DB`). Files prefixed with _ are not routes.

export function json(obj, status, headers) {
  return new Response(JSON.stringify(obj), {
    status: status || 200,
    headers: Object.assign({ "content-type": "application/json; charset=utf-8" }, headers || {}),
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
export async function settleAll(env, data) {
  const decided = {};
  (data.matches || []).forEach((m) => { if (m.decided) decided[m.num] = m.winner; });
  if (!Object.keys(decided).length) return;
  const open = (await env.DB.prepare("SELECT * FROM bets WHERE status='open'").all()).results || [];
  const stmts = [];
  for (const b of open) {
    if (!(b.match_num in decided)) continue;
    const won = decided[b.match_num] === b.pick;
    const payout = won ? round2(b.stake * b.odds) : 0;
    stmts.push(env.DB.prepare("UPDATE bets SET status=?, payout=? WHERE id=?")
      .bind(won ? "won" : "lost", payout, b.id));
    if (won) stmts.push(env.DB.prepare("UPDATE players SET balance=balance+? WHERE id=?")
      .bind(payout, b.player_id));
  }
  if (stmts.length) await env.DB.batch(stmts);
}
