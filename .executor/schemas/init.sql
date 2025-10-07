-- .executor/memory/schemas/init.sql

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- 1) facts: atomic observations (preferences, habits, context, system, repair notes)
CREATE TABLE IF NOT EXISTS facts (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     TEXT,
  session_id  TEXT,
  type        TEXT NOT NULL,       -- 'preference' | 'habit' | 'context' | 'system' | 'repair' | ...
  key         TEXT NOT NULL,
  value       TEXT NOT NULL,
  confidence  REAL DEFAULT 1.0,
  source      TEXT,                -- 'chat' | 'scheduler' | 'self_healer' | 'router' | ...
  timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP,
  expires_at  DATETIME,
  active      INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_facts_type_key          ON facts(type, key);
CREATE INDEX IF NOT EXISTS idx_facts_user_session_time ON facts(user_id, session_id, timestamp DESC);

-- 2) preferences: durable promoted facts
CREATE TABLE IF NOT EXISTS preferences (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id      TEXT,
  category     TEXT NOT NULL,
  key          TEXT NOT NULL,
  value        TEXT NOT NULL,
  weight       REAL DEFAULT 1.0,
  updated_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
  origin_fact  INTEGER REFERENCES facts(id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_prefs_user_key ON preferences(user_id, key);
CREATE INDEX IF NOT EXISTS idx_prefs_category      ON preferences(category);

-- 3) repairs: self-healer memory of issues and outcomes
CREATE TABLE IF NOT EXISTS repairs (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     TEXT,
  file        TEXT NOT NULL,
  error       TEXT NOT NULL,
  fix_summary TEXT,
  success     INTEGER NOT NULL DEFAULT 0, -- 1 if tests green after fix
  created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_repairs_file_time ON repairs(file, created_at DESC);

-- 4) conversations: optional long-form turn history
CREATE TABLE IF NOT EXISTS conversations (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id   TEXT,
  session   TEXT NOT NULL,
  role      TEXT NOT NULL, -- 'user' | 'assistant' | 'system'
  content   TEXT NOT NULL,
  timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_conv_session_time ON conversations(session, timestamp DESC);

-- 5) embeddings: future semantic memory (placeholder table)
CREATE TABLE IF NOT EXISTS embeddings (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  fact_id    INTEGER NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
  model      TEXT NOT NULL,
  vector     BLOB NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_embed_fact ON embeddings(fact_id);
