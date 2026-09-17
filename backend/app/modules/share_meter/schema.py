"""share_meter 模块的库表结构与 readings 表迁移。

ensure_schema 幂等：seed 建库时调用，服务层启动时也会兜底调用；
对老库通过 ALTER TABLE 补齐 readings 的分摊溯源列。
"""

import sqlite3

DDL = """
CREATE TABLE IF NOT EXISTS share_plans(
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    master_account_id INTEGER NOT NULL,
    remainder_account_id INTEGER NOT NULL,
    created_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS share_plan_members(
    id INTEGER PRIMARY KEY,
    plan_id INTEGER NOT NULL,
    account_id INTEGER NOT NULL,
    pct INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS share_runs(
    id INTEGER PRIMARY KEY,
    plan_id INTEGER NOT NULL,
    period TEXT NOT NULL,
    master_kwh REAL NOT NULL,
    allocated_kwh REAL NOT NULL,
    remainder_kwh REAL NOT NULL,
    remainder_account_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    superseded_by INTEGER,
    created_at TEXT
);
"""

# readings 溯源列：period 账期、source 来源(manual/share)、share_run_id 分摊记录、superseded 软作废
READING_COLUMNS = [
    ("period", "TEXT"),
    ("source", "TEXT NOT NULL DEFAULT 'manual'"),
    ("share_run_id", "INTEGER"),
    ("superseded", "INTEGER NOT NULL DEFAULT 0"),
]


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(r[1] == column for r in conn.execute(f"PRAGMA table_info({table})").fetchall())


def _has_table(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)
    if _has_table(conn, "readings"):
        for name, ddl in READING_COLUMNS:
            if not _has_column(conn, "readings", name):
                conn.execute(f"ALTER TABLE readings ADD COLUMN {name} {ddl}")
    conn.commit()
