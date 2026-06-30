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
  if (!m || m.decided || (ko !== null && ko <= Date.now())) return json({ ok: false, error: "closed" });

  await env.DB.batch([
    env.DB.prepare("UPDATE players SET balance=balance+? WHERE id=?").bind(bet.stake, me.id),
    env.DB.prepare("DELETE FROM bets WHERE id=?").bind(id),
  ]);
  return json({ ok: true });
}
