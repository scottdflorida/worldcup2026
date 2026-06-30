// POST /api/bets/leave — leave the pool identified by the active token: delete the
// player and their bets. The client then drops the membership from its local list.
import { json, getPlayer } from "./_common.js";

export async function onRequestPost({ request, env }) {
  if (!env || !env.DB) return json({ ok: false, error: "not_configured" });
  const me = await getPlayer(env, request);
  if (!me) return json({ ok: false, error: "not_joined" });
  await env.DB.batch([
    env.DB.prepare("DELETE FROM bets WHERE player_id=?").bind(me.id),
    env.DB.prepare("DELETE FROM players WHERE id=?").bind(me.id),
  ]);
  return json({ ok: true });
}
