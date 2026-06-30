// POST /api/bets/update {id, pick, stake} — change an open bet's pick/stake before
// kickoff. Re-locks the odds at the current line, refunds the old stake, charges
// the new one. Same no-hedging rule against your other open bets on that match.
import { json, loadData, getPlayer, settleAll, round2 } from "./_common.js";

export async function onRequestPost({ request, env }) {
  if (!env || !env.DB) return json({ ok: false, error: "not_configured" });
  let me = await getPlayer(env, request);
  if (!me) return json({ ok: false, error: "not_joined" });

  let body = {};
  try { body = await request.json(); } catch (e) { /* ignore */ }
  const id = parseInt(body.id, 10);
  const pick = (body.pick || "").toString();
  const stake = round2(body.stake);

  const data = await loadData(request);
  await settleAll(env, data);
  me = await env.DB.prepare("SELECT * FROM players WHERE id=?").bind(me.id).first();

  const bet = await env.DB.prepare("SELECT * FROM bets WHERE id=? AND player_id=? AND status='open'")
    .bind(id, me.id).first();
  if (!bet) return json({ ok: false, error: "no_bet" });
  const m = (data.matches || []).find((x) => x.num === bet.match_num);
  if (!m) return json({ ok: false, error: "no_match" });
  const ko = m.kickoff ? Date.parse(m.kickoff) : null;
  if (m.decided || (ko !== null && ko <= Date.now())) return json({ ok: false, error: "closed" });
  if (pick !== m.team1 && pick !== m.team2) return json({ ok: false, error: "bad_pick" });
  if (!(stake > 0)) return json({ ok: false, error: "bad_stake" });
  const others = (await env.DB.prepare(
    "SELECT pick FROM bets WHERE player_id=? AND match_num=? AND id<>? AND status='open'")
    .bind(me.id, bet.match_num, id).all()).results || [];
  if (others.some((r) => r.pick !== pick)) return json({ ok: false, error: "both_sides" });
  const avail = me.balance + bet.stake;             // old stake is refunded
  if (stake > avail + 1e-9) return json({ ok: false, error: "insufficient" });

  const odds = pick === m.team1 ? m.odds1 : m.odds2;
  await env.DB.batch([
    env.DB.prepare("UPDATE players SET balance=balance+?-? WHERE id=?").bind(bet.stake, stake, me.id),
    env.DB.prepare("UPDATE bets SET pick=?, odds=?, stake=? WHERE id=?").bind(pick, odds, stake, id),
  ]);
  return json({ ok: true, balance: round2(me.balance + bet.stake - stake) });
}
