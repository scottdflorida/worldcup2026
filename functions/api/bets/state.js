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
      odds1: m.odds1, odds2: m.odds2, kickoff: m.kickoff, decided: m.decided,
      winner: m.winner, open: !m.decided && (ko === null || ko > now),
    };
  });

  const resp = { ok: true, configured: true, joined: false, flags: data.flags || {}, matches };
  const me = await getPlayer(env, request);
  if (me) {
    resp.joined = true;
    resp.token = me.token;            // so the client can store/migrate this membership
    const pool = await env.DB.prepare("SELECT * FROM pools WHERE id=?").bind(me.pool_id).first();
    resp.pool = { name: pool ? pool.name : "", code: pool ? pool.code : "" };
    // all pool bets (incl odds) — drives poolBets, lockedCounts, and portfolio value
    const all = (await env.DB.prepare(
      "SELECT b.match_num,b.pick,b.stake,b.odds,b.status,b.payout,b.player_id,p.name FROM bets b " +
      "JOIN players p ON p.id=b.player_id WHERE p.pool_id=? ORDER BY b.id ASC")
      .bind(me.pool_id).all()).results || [];
    // portfolio = potential return (stake*odds) on each player's still-open bets
    const openVal = {};
    for (const r of all) if (r.status === "open") openVal[r.player_id] = (openVal[r.player_id] || 0) + r.stake * r.odds;
    const port = (id) => openVal[id] || 0;
    resp.me = { name: me.name, cash: round2(me.balance), portfolio: round2(port(me.id)),
                total: round2(me.balance + port(me.id)), out: me.balance + port(me.id) <= 0 };
    // leaderboard ranked by total = cash + portfolio
    const players = (await env.DB.prepare("SELECT id,name,balance FROM players WHERE pool_id=?")
      .bind(me.pool_id).all()).results || [];
    resp.leaderboard = players.map((p) => ({
      name: p.name, cash: round2(p.balance), portfolio: round2(port(p.id)),
      total: round2(p.balance + port(p.id)), out: p.balance + port(p.id) <= 0, you: p.id === me.id,
    })).sort((a, b) => b.total - a.total || a.name.localeCompare(b.name));
    const mb = (await env.DB.prepare(
      "SELECT match_num,pick,stake,odds,status,payout FROM bets WHERE player_id=? ORDER BY id DESC")
      .bind(me.id).all()).results || [];
    resp.myBets = mb.map((b) => ({
      match_num: b.match_num, pick: b.pick, stake: round2(b.stake),
      odds: b.odds, status: b.status, payout: round2(b.payout),
    }));
    // everyone's bets — but only on matches the viewer is allowed to see: any
    // decided match, or an open match they've already bet on themselves. Open
    // matches they haven't bet on just expose a hidden-bet COUNT (no picks).
    const decided = new Set(matches.filter((m) => m.decided).map((m) => m.num));
    const mine = new Set(mb.map((b) => b.match_num));
    const revealed = new Set([...decided, ...mine]);
    resp.poolBets = all.filter((r) => revealed.has(r.match_num)).map((r) => ({
      player: r.name, you: r.player_id === me.id, match_num: r.match_num,
      pick: r.pick, stake: round2(r.stake), status: r.status, payout: round2(r.payout),
    }));
    const locked = {};
    for (const r of all) if (!revealed.has(r.match_num)) locked[r.match_num] = (locked[r.match_num] || 0) + 1;
    resp.lockedCounts = locked;
  }
  return json(resp);
}
