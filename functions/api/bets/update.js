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
  // The net balance move is (old stake - new stake): only the DELTA between the two
  // stakes ever hits the balance, so we guard just that, and always move money in
  // the SAFE direction first (never favouring overspend). The bet flip is guarded
  // on status='open' so we never mutate a bet a concurrent settle/cancel just took.
  const delta = round2(stake - bet.stake);
  if (delta > 0) {
    // Net debit: charge the extra first, guarded on affordability (this is the real
    // double-spend defense — the read-check above is just a fast early reject).
    const debit = await env.DB.prepare(
      "UPDATE players SET balance=balance-? WHERE id=? AND balance>=?-1e-9")
      .bind(delta, me.id, delta).run();
    if (!debit.meta || debit.meta.changes !== 1) return json({ ok: false, error: "insufficient" });
    const flip = await env.DB.prepare(
      "UPDATE bets SET pick=?, odds=?, stake=? WHERE id=? AND player_id=? AND status='open'")
      .bind(pick, odds, stake, id, me.id).run();
    if (!flip.meta || flip.meta.changes !== 1) {
      // The bet was settled/cancelled between our read and the flip: compensate by
      // refunding the extra charge so it isn't stranded on a bet we didn't modify.
      await env.DB.prepare("UPDATE players SET balance=balance+? WHERE id=?").bind(delta, me.id).run();
      return json({ ok: false, error: "no_bet" });
    }
  } else {
    // Net refund (or unchanged stake): flip the bet first, and credit the refund
    // ONLY if we actually claimed an open bet — so a concurrent settle/cancel can't
    // trigger a phantom refund. A refund can never fail on affordability.
    const flip = await env.DB.prepare(
      "UPDATE bets SET pick=?, odds=?, stake=? WHERE id=? AND player_id=? AND status='open'")
      .bind(pick, odds, stake, id, me.id).run();
    if (!flip.meta || flip.meta.changes !== 1) return json({ ok: false, error: "no_bet" });
    const refund = round2(bet.stake - stake);
    if (refund > 0) await env.DB.prepare("UPDATE players SET balance=balance+? WHERE id=?").bind(refund, me.id).run();
  }

  const fresh = await env.DB.prepare("SELECT balance FROM players WHERE id=?").bind(me.id).first();
  return json({ ok: true, balance: round2(fresh ? fresh.balance : me.balance + bet.stake - stake) });
}
