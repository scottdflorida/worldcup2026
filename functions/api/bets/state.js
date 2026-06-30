// GET /api/bets/state — pool snapshot: bettable matches, the caller's balance &
// bets, and the leaderboard. Settles any decided bets first so balances are live.
import { json, loadData, getPlayer, settleAll, round2 } from "./_common.js";

export async function onRequestGet({ request, env }) {
  if (!env || !env.DB) return json({ ok: true, configured: false });

  const data = await loadData(request);
  await settleAll(env, data);

  const now = Date.now();
  const matches = (data.matches || []).map((m) => {
    const ko = m.kickoff ? Date.parse(m.kickoff) : null;
    return {
      num: m.num, round: m.round, team1: m.team1, team2: m.team2,
      odds1: m.odds1, odds2: m.odds2, decided: m.decided, winner: m.winner,
      open: !m.decided && (ko === null || ko > now),
    };
  });

  const resp = { ok: true, configured: true, joined: false, flags: data.flags || {}, matches };
  const me = await getPlayer(env, request);
  if (me) {
    resp.joined = true;
    resp.me = { name: me.name, balance: round2(me.balance), out: me.balance <= 0 };
    const pool = await env.DB.prepare("SELECT * FROM pools WHERE id=?").bind(me.pool_id).first();
    resp.pool = { name: pool ? pool.name : "" };
    const lb = (await env.DB.prepare(
      "SELECT id,name,balance FROM players WHERE pool_id=? ORDER BY balance DESC, name ASC")
      .bind(me.pool_id).all()).results || [];
    resp.leaderboard = lb.map((p) => ({ name: p.name, balance: round2(p.balance), you: p.id === me.id }));
    const mb = (await env.DB.prepare(
      "SELECT match_num,pick,stake,odds,status,payout FROM bets WHERE player_id=? ORDER BY id DESC")
      .bind(me.id).all()).results || [];
    resp.myBets = mb.map((b) => ({
      match_num: b.match_num, pick: b.pick, stake: round2(b.stake),
      odds: b.odds, status: b.status, payout: round2(b.payout),
    }));
  }
  return json(resp);
}
