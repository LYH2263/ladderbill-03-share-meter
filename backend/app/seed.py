import json

from app.db import connect
from app.engines.peak_compare import compare_plain_vs_peak
from app.engines.tier_progressive import calc_bill

# readings 表在合表分摊模块中新增的列：
# period               账期 YYYY-MM（手工抄表可为空）
# source               来源：manual=手工抄表 / shared=合表分摊产生
# share_allocation_id  来源分摊单 id
# superseded           软标记：1=已被重算作废（保留行，不物理删除）
_READING_NEW_COLUMNS = {
    "period": "TEXT",
    "source": "TEXT NOT NULL DEFAULT 'manual'",
    "share_allocation_id": "INTEGER",
    "superseded": "INTEGER NOT NULL DEFAULT 0",
}


def _migrate_readings(conn):
    """对已存在的 readings 表补齐新列（CREATE TABLE IF NOT EXISTS 不会加列）。"""
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(readings)").fetchall()}
    for column, ddl in _READING_NEW_COLUMNS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE readings ADD COLUMN {column} {ddl}")
    conn.commit()


def init_db():
    conn = connect()
    conn.executescript(
        """
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS accounts(
        id INTEGER PRIMARY KEY, name TEXT, meter_no TEXT, note TEXT);
    CREATE TABLE IF NOT EXISTS readings(id INTEGER PRIMARY KEY, account_id INTEGER, kwh REAL, peak INTEGER);
    CREATE TABLE IF NOT EXISTS tiers(id INTEGER PRIMARY KEY, up_to REAL, price REAL, sort_order INTEGER);
    CREATE TABLE IF NOT EXISTS calc_runs(
        id INTEGER PRIMARY KEY,
        kind TEXT,
        account_id INTEGER,
        input_json TEXT,
        result_json TEXT,
        created_at TEXT
    );

    -- 合表分摊方案：主表电量来源户 + 余数（除不尽电量）归属成员
    CREATE TABLE IF NOT EXISTS share_schemes(
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        master_account_id INTEGER NOT NULL,
        remainder_account_id INTEGER NOT NULL,
        created_at TEXT,
        updated_at TEXT
    );
    CREATE TABLE IF NOT EXISTS share_scheme_members(
        id INTEGER PRIMARY KEY,
        scheme_id INTEGER NOT NULL,
        account_id INTEGER NOT NULL,
        ratio INTEGER NOT NULL,
        sort_order INTEGER NOT NULL DEFAULT 0,
        UNIQUE(scheme_id, account_id)
    );
    -- 按账期执行一次分摊生成一张分摊单
    CREATE TABLE IF NOT EXISTS share_allocations(
        id INTEGER PRIMARY KEY,
        scheme_id INTEGER NOT NULL,
        period TEXT NOT NULL,
        master_kwh REAL NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        superseded_by_id INTEGER,
        created_at TEXT
    );
    -- 同一方案同一账期只允许一张生效中的分摊单（重算后旧单置为 superseded）
    CREATE UNIQUE INDEX IF NOT EXISTS idx_share_active_period
        ON share_allocations(scheme_id, period) WHERE status='active';
    CREATE TABLE IF NOT EXISTS share_allocation_lines(
        id INTEGER PRIMARY KEY,
        allocation_id INTEGER NOT NULL,
        account_id INTEGER NOT NULL,
        ratio INTEGER NOT NULL,
        base_kwh REAL NOT NULL,
        remainder_kwh REAL NOT NULL,
        allocated_kwh REAL NOT NULL,
        reading_id INTEGER,
        sort_order INTEGER NOT NULL DEFAULT 0
    );
    """
    )
    _migrate_readings(conn)
    if conn.execute("SELECT COUNT(*) c FROM accounts").fetchone()["c"] == 0:
        conn.execute(
            "INSERT INTO accounts(name, meter_no, note) VALUES ('张家', 'M-1001', '对照：正常用量')"
        )
        conn.execute(
            "INSERT INTO accounts(name, meter_no, note) VALUES ('李家(种子偏高)', 'M-1002', '对照：高用量+尖峰')"
        )
        conn.execute(
            "INSERT INTO accounts(name, meter_no, note) VALUES ('王家', 'M-1003', '合表分户示例')"
        )
        conn.executemany(
            "INSERT INTO tiers(up_to, price, sort_order) VALUES (?,?,?)",
            [(180, 0.52, 1), (260, 0.62, 2), (None, 0.82, 3)],
        )
        conn.execute("INSERT INTO readings(account_id, kwh, peak) VALUES (1, 120, 0)")
        conn.execute("INSERT INTO readings(account_id, kwh, peak) VALUES (2, 400, 1)")
        conn.execute("INSERT INTO settings(key, value) VALUES ('peak_factor', '1.2')")
        conn.execute("INSERT INTO settings(key, value) VALUES ('currency', 'CNY')")
        # 合表分摊演示方案（尚未执行）：张家总表，张/李/王按 40/30/30 分摊，除不尽电量归张家
        now = _utcnow()
        cur = conn.execute(
            "INSERT INTO share_schemes(name, master_account_id, remainder_account_id, created_at, updated_at)"
            " VALUES ('一号总表合摊', 1, 1, ?, ?)",
            (now, now),
        )
        scheme_id = int(cur.lastrowid)
        conn.executemany(
            "INSERT INTO share_scheme_members(scheme_id, account_id, ratio, sort_order) VALUES (?,?,?,?)",
            [(scheme_id, 1, 40, 0), (scheme_id, 2, 30, 1), (scheme_id, 3, 30, 2)],
        )
        tiers = [{"up_to": r[0], "price": r[1]} for r in [(180, 0.52), (260, 0.62), (None, 0.82)]]
        bill1 = calc_bill(120, tiers, 1.0)
        conn.execute(
            "INSERT INTO calc_runs(kind, account_id, input_json, result_json, created_at) VALUES (?,?,?,?,datetime('now'))",
            ("bill", 1, json.dumps({"kwh": 120, "peak": False}), json.dumps(bill1, ensure_ascii=False)),
        )
        cmp2 = compare_plain_vs_peak(400, tiers, 1.2)
        conn.execute(
            "INSERT INTO calc_runs(kind, account_id, input_json, result_json, created_at) VALUES (?,?,?,?,datetime('now'))",
            ("compare", 2, json.dumps({"kwh": 400}), json.dumps(cmp2, ensure_ascii=False)),
        )
        conn.commit()
    conn.close()


def _utcnow() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
