-- Cloudflare D1 schema for the play-money betting pool.
-- Apply with:  npx wrangler d1 execute wc-bets --remote --file=./schema.sql
CREATE TABLE IF NOT EXISTS pools (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  code       TEXT UNIQUE NOT NULL,
  name       TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS players (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  pool_id    INTEGER NOT NULL,
  name       TEXT NOT NULL,
  token      TEXT UNIQUE NOT NULL,
  balance    REAL NOT NULL DEFAULT 100,
  created_at TEXT NOT NULL,
  UNIQUE(pool_id, name)
);
CREATE TABLE IF NOT EXISTS bets (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  player_id  INTEGER NOT NULL,
  match_num  INTEGER NOT NULL,
  pick       TEXT NOT NULL,
  stake      REAL NOT NULL,
  odds       REAL NOT NULL,
  status     TEXT NOT NULL DEFAULT 'open',   -- open | won | lost
  payout     REAL NOT NULL DEFAULT 0,
  placed_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_players_pool ON players(pool_id);
CREATE INDEX IF NOT EXISTS idx_bets_player  ON bets(player_id);
CREATE INDEX IF NOT EXISTS idx_bets_status  ON bets(status);
