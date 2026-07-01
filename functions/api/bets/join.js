// POST /api/bets/join {name, code} — join (or create) a pool with $100 and set a
// private player token cookie. Lightweight identity: no password, friends only.
import { json, newToken, tokenCookie } from "./_common.js";

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
  // Reclaim, don't block. This is a passwordless friends pool, so name + pool
  // code IS the re-entry credential: returning on a new device or after the
  // browser dropped localStorage should log you back into your existing player
  // (same balance + bets), not get rejected as "name_taken" and lock you out.
  // Case-insensitive so "Lo"/"lo" resolve to the same person (and never split
  // into two players), returning the stored spelling as canonical.
  const existing = await env.DB.prepare(
    "SELECT token, name FROM players WHERE pool_id=? AND name=? COLLATE NOCASE")
    .bind(pool.id, name).first();
  if (existing) {
    return json({ ok: true, token: existing.token, code, name: existing.name, reclaimed: true },
                200, { "Set-Cookie": tokenCookie(existing.token) });
  }

  const token = newToken();
  await env.DB.prepare("INSERT INTO players(pool_id,name,token,balance,created_at) VALUES(?,?,?,100,?)")
    .bind(pool.id, name, token, now).run();

  // the client stores this token as a membership and sends it as X-Bet-Token;
  // the cookie is a same-device fallback for when localStorage is lost.
  return json({ ok: true, token, code, name }, 200, { "Set-Cookie": tokenCookie(token) });
}
