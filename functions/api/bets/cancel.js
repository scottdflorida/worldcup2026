// POST /api/bets/cancel {id} — remove an open bet before kickoff and refund the
// stake to cash.
import { json, loadData, getPlayer, settleAll } from "./_common.js";

export async function onRequestPost({ request, env }) {
  if (!env || !env.DB) return json({ ok: false, error: "not_configured" });
  const me = await getPlayer(env, request);
  if (!me) return json({ ok: false, error: "not_joined" });

  let body = {};
  try { body = await request.json(); } catch (e) { /* ignore */ }
  const id = parseInt(body.id, 10);

  const data = await loadData(request);
  await settleAll(env, data);
  const bet = await env.DB.prepare("SELECT * FROM bets WHERE id=? AND player_id=? AND status='open'")
    .bind(id, me.id).first();
  if (!bet) return json({ ok: false, error: "no_bet" });
  const m = (data.matches || []).find((x) => x.num === bet.match_num);
  const ko = m && m.kickoff ? Date.parse(m.kickoff) : null;
  // winner-set and null-kickoff are closed too: a stale edge-cached bets-data.json
  // can lag `decided`, and a knockout entry with an unparseable clock should fail
  // safe rather than stay cancellable forever.
  if (!m || m.decided || m.winner || ko === null || ko <= Date.now()) return json({ ok: false, error: "closed" });

  // Guarded delete first, refund second: the DELETE claims the row only if it is
  // still 'open', so exactly one caller can win (vs a concurrent cancel/settle).
  // RETURNING stake refunds the row's LIVE stake — not the value read above —
  // so a concurrent /update changing the stake can't cause an over/under-refund.
  const del = await env.DB.prepare(
    "DELETE FROM bets WHERE id=? AND player_id=? AND status='open' RETURNING stake")
    .bind(id, me.id).first();
  if (!del) return json({ ok: false, error: "no_bet" });
  await env.DB.prepare("UPDATE players SET balance=balance+? WHERE id=?").bind(del.stake, me.id).run();
  return json({ ok: true });
}
