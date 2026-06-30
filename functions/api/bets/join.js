// POST /api/bets/join {name, code} — join (or create) a pool with $100 and set a
// private player token cookie. Lightweight identity: no password, friends only.
import { json, newToken } from "./_common.js";

export async function onRequestPost({ request, env }) {
  if (!env || !env.DB) return json({ ok: false, error: "not_configured" });
  let body = {};
  try { body = await request.json(); } catch (e) { /* ignore */ }
  const name = (body.name || "").toString().trim().slice(0, 24);
  const code = (body.code || "").toString().trim().slice(0, 24).toLowerCase();
  if (!name || !code) return json({ ok: false, error: "missing" });

  const now = new Date().toISOString();
  let pool = await env.DB.prepare("SELECT * FROM pools WHERE code=?").bind(code).first();
  if (!pool) {
    await env.DB.prepare("INSERT INTO pools(code,name,created_at) VALUES(?,?,?)")
      .bind(code, code, now).run();
    pool = await env.DB.prepare("SELECT * FROM pools WHERE code=?").bind(code).first();
  }
  const taken = await env.DB.prepare("SELECT id FROM players WHERE pool_id=? AND name=?")
    .bind(pool.id, name).first();
  if (taken) return json({ ok: false, error: "name_taken" });

  const token = newToken();
  await env.DB.prepare("INSERT INTO players(pool_id,name,token,balance,created_at) VALUES(?,?,?,100,?)")
    .bind(pool.id, name, token, now).run();

  return json({ ok: true }, 200, {
    "Set-Cookie": "wc_bet=" + token + "; Path=/; Max-Age=31536000; SameSite=Lax; HttpOnly",
  });
}
