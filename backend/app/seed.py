import json

from app.db import connect
from app.engines.peak_compare import compare_plain_vs_peak
from app.engines.tier_progressive import calc_bill
from app.modules import share_meter


def init_db():
    conn = connect()
    conn.executescript(
        """
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS accounts(
        id INTEGER PRIMARY KEY, name TEXT, meter_no TEXT, note TEXT);
    CREATE TABLE IF NOT EXISTS readings(
        id INTEGER PRIMARY KEY, account_id INTEGER, kwh REAL, peak INTEGER,
        period TEXT, source TEXT NOT NULL DEFAULT 'manual',
        share_run_id INTEGER, superseded INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS tiers(id INTEGER PRIMARY KEY, up_to REAL, price REAL, sort_order INTEGER);
    CREATE TABLE IF NOT EXISTS calc_runs(
        id INTEGER PRIMARY KEY,
        kind TEXT,
        account_id INTEGER,
        input_json TEXT,
        result_json TEXT,
        created_at TEXT
    );
    """
    )
    share_meter.ensure_schema(conn)
    if conn.execute("SELECT COUNT(*) c FROM accounts").fetchone()["c"] == 0:
        conn.execute(
            "INSERT INTO accounts(name, meter_no, note) VALUES ('张家', 'M-1001', '对照：正常用量')"
        )
        conn.execute(
            "INSERT INTO accounts(name, meter_no, note) VALUES ('李家(种子偏高)', 'M-1002', '对照：高用量+尖峰')"
        )
        conn.execute(
            "INSERT INTO accounts(name, meter_no, note) VALUES ('合表总表户', 'M-1003', '合表：总表电量来源户')"
        )
        conn.executemany(
            "INSERT INTO tiers(up_to, price, sort_order) VALUES (?,?,?)",
            [(180, 0.52, 1), (260, 0.62, 2), (None, 0.82, 3)],
        )
        conn.execute("INSERT INTO readings(account_id, kwh, peak) VALUES (1, 120, 0)")
        conn.execute("INSERT INTO readings(account_id, kwh, peak) VALUES (2, 400, 1)")
        conn.execute(
            "INSERT INTO readings(account_id, kwh, peak, period) VALUES (3, 1000, 0, '2026-08')"
        )
        conn.execute("INSERT INTO settings(key, value) VALUES ('peak_factor', '1.2')")
        conn.execute("INSERT INTO settings(key, value) VALUES ('currency', 'CNY')")
        conn.execute(
            "INSERT INTO share_plans(name, master_account_id, remainder_account_id, created_at, updated_at)"
            " VALUES ('家属院合表方案', 3, 1, datetime('now'), datetime('now'))"
        )
        conn.executemany(
            "INSERT INTO share_plan_members(plan_id, account_id, pct) VALUES (1, ?, ?)",
            [(1, 60), (2, 40)],
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
