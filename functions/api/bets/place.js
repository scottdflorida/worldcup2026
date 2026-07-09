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
  // winner/null-kickoff closed too — see cancel.js for the stale-cache rationale.
  if (m.decided || m.winner || ko === null || ko <= Date.now()) return json({ ok: false, error: "closed" });
  if (pick !== m.team1 && pick !== m.team2) return json({ ok: false, error: "bad_pick" });
  if (!(stake > 0)) return json({ ok: false, error: "bad_stake" });
  if (stake > me.balance + 1e-9) return json({ ok: false, error: "insufficient" });
  // no hedging: can't back both teams in the same tie (more on the same side is fine)
  const prior = (await env.DB.prepare("SELECT pick FROM bets WHERE player_id=? AND match_num=?")
    .bind(me.id, matchNum).all()).results || [];
  if (prior.some((r) => r.pick !== pick)) return json({ ok: false, error: "both_sides" });

  const odds = pick === m.team1 ? m.odds1 : m.odds2;
  const now = new Date().toISOString();

  // Guarded debit: subtract the stake ONLY if the balance still covers it, in a
  // single conditional write. The read-check above is a fast early reject; THIS is
  // the authoritative one — two concurrent places can no longer both pass a stale
  // read and overdraw, because SQLite serializes the writes and the second finds
  // balance too low and claims 0 rows.
  const debit = await env.DB.prepare(
    "UPDATE players SET balance=balance-? WHERE id=? AND balance>=?-1e-9")
    .bind(stake, me.id, stake).run();
  if (!debit.meta || debit.meta.changes !== 1) return json({ ok: false, error: "insufficient" });

  // Debit-first-then-insert (not one batch): a batch can't skip the insert when
  // the guarded debit claims 0 rows, which would orphan a bet with no debit. If the
  // insert fails after a successful debit, compensate with a refund so the stake is
  // never stranded on a phantom debit.
  try {
    await env.DB.prepare(
      "INSERT INTO bets(player_id,match_num,pick,stake,odds,status,payout,placed_at) VALUES(?,?,?,?,?,'open',0,?)")
      .bind(me.id, matchNum, pick, stake, odds, now).run();
  } catch (e) {
    await env.DB.prepare("UPDATE players SET balance=balance+? WHERE id=?").bind(stake, me.id).run();
    return json({ ok: false, error: "place_failed" });
  }

  const fresh = await env.DB.prepare("SELECT balance FROM players WHERE id=?").bind(me.id).first();
  return json({ ok: true, balance: round2(fresh ? fresh.balance : me.balance - stake) });
}
