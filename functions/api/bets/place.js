// POST /api/bets/place {match, pick, stake} — wager on a match winner. Validates
// server-side, snapshots the current odds onto the bet, and deducts the stake.
import { json, loadData, getPlayer, settleAll, round2 } from "./_common.js";

export async function onRequestPost({ request, env }) {
  if (!env || !env.DB) return json({ ok: false, error: "not_configured" });
  let me = await getPlayer(env, request);
  if (!me) return json({ ok: false, error: "not_joined" });

  let body = {};
  try { body = await request.json(); } catch (e) { /* ignore */ }
  const matchNum = parseInt(body.match, 10);
  const pick = (body.pick || "").toString();
  const stake = round2(body.stake);

  const data = await loadData(request);
  await settleAll(env, data);                 // settle first so balance is current
  me = await env.DB.prepare("SELECT * FROM players WHERE id=?").bind(me.id).first();

  const m = (data.matches || []).find((x) => x.num === matchNum);
  if (!m) return json({ ok: false, error: "no_match" });
  const ko = m.kickoff ? Date.parse(m.kickoff) : null;
  if (m.decided || (ko !== null && ko <= Date.now())) return json({ ok: false, error: "closed" });
  if (pick !== m.team1 && pick !== m.team2) return json({ ok: false, error: "bad_pick" });
  if (!(stake > 0)) return json({ ok: false, error: "bad_stake" });
  if (stake > me.balance + 1e-9) return json({ ok: false, error: "insufficient" });
  // no hedging: can't back both teams in the same tie (more on the same side is fine)
  const prior = (await env.DB.prepare("SELECT pick FROM bets WHERE player_id=? AND match_num=?")
    .bind(me.id, matchNum).all()).results || [];
  if (prior.some((r) => r.pick !== pick)) return json({ ok: false, error: "both_sides" });

  const odds = pick === m.team1 ? m.odds1 : m.odds2;
  const now = new Date().toISOString();
  await env.DB.batch([
    env.DB.prepare("UPDATE players SET balance=balance-? WHERE id=?").bind(stake, me.id),
    env.DB.prepare(
      "INSERT INTO bets(player_id,match_num,pick,stake,odds,status,payout,placed_at) VALUES(?,?,?,?,?,'open',0,?)")
      .bind(me.id, matchNum, pick, stake, odds, now),
  ]);
  return json({ ok: true, balance: round2(me.balance - stake) });
}
