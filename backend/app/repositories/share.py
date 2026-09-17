"""合表分摊仓储：方案 / 成员 / 分摊单 / 分摊抄表的落库操作。

沿用项目惯例：无状态函数，入参 conn，边界处 sqlite3.Row -> dict。
"""
import sqlite3
from datetime import datetime, timezone


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------- 方案 ----------

def list_schemes(conn: sqlite3.Connection) -> list[dict]:
    q = """
    SELECT s.*,
           ma.name AS master_account_name, ma.meter_no AS master_meter_no,
           ra.name AS remainder_account_name,
           (SELECT COUNT(*) FROM share_scheme_members m WHERE m.scheme_id=s.id) AS member_count
      FROM share_schemes s
      JOIN accounts ma ON ma.id=s.master_account_id
      JOIN accounts ra ON ra.id=s.remainder_account_id
     ORDER BY s.id
    """
    return [dict(r) for r in conn.execute(q).fetchall()]


def get_scheme(conn: sqlite3.Connection, scheme_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM share_schemes WHERE id=?", (scheme_id,)).fetchone()
    if not row:
        return None
    scheme = dict(row)
    members = conn.execute(
        """
        SELECT m.id, m.scheme_id, m.account_id, m.ratio, m.sort_order,
               a.name AS account_name, a.meter_no
          FROM share_scheme_members m
          JOIN accounts a ON a.id=m.account_id
         WHERE m.scheme_id=?
         ORDER BY m.sort_order, m.id
        """,
        (scheme_id,),
    ).fetchall()
    scheme["members"] = [dict(r) for r in members]
    master = conn.execute(
        "SELECT id, name, meter_no FROM accounts WHERE id=?", (scheme["master_account_id"],)
    ).fetchone()
    scheme["master_account"] = dict(master) if master else None
    return scheme


def insert_scheme(
    conn: sqlite3.Connection,
    name: str,
    master_account_id: int,
    remainder_account_id: int,
    members: list[dict],
) -> int:
    now = _utcnow()
    cur = conn.execute(
        """INSERT INTO share_schemes(name, master_account_id, remainder_account_id, created_at, updated_at)
           VALUES (?,?,?,?,?)""",
        (name, master_account_id, remainder_account_id, now, now),
    )
    scheme_id = int(cur.lastrowid)
    conn.executemany(
        "INSERT INTO share_scheme_members(scheme_id, account_id, ratio, sort_order) VALUES (?,?,?,?)",
        [
            (scheme_id, m["account_id"], m["ratio"], idx)
            for idx, m in enumerate(members)
        ],
    )
    conn.commit()
    return scheme_id


def update_scheme(
    conn: sqlite3.Connection,
    scheme_id: int,
    name: str,
    master_account_id: int,
    remainder_account_id: int,
    members: list[dict],
) -> None:
    conn.execute(
        """UPDATE share_schemes
              SET name=?, master_account_id=?, remainder_account_id=?, updated_at=?
            WHERE id=?""",
        (name, master_account_id, remainder_account_id, _utcnow(), scheme_id),
    )
    conn.execute("DELETE FROM share_scheme_members WHERE scheme_id=?", (scheme_id,))
    conn.executemany(
        "INSERT INTO share_scheme_members(scheme_id, account_id, ratio, sort_order) VALUES (?,?,?,?)",
        [(scheme_id, m["account_id"], m["ratio"], idx) for idx, m in enumerate(members)],
    )
    conn.commit()


# ---------- 分摊单 ----------

def find_active_allocation(conn: sqlite3.Connection, scheme_id: int, period: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM share_allocations WHERE scheme_id=? AND period=? AND status='active'",
        (scheme_id, period),
    ).fetchone()
    return dict(row) if row else None


def _load_lines(conn: sqlite3.Connection, allocation_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT l.*, a.name AS account_name, a.meter_no
          FROM share_allocation_lines l
          JOIN accounts a ON a.id=l.account_id
         WHERE l.allocation_id=?
         ORDER BY l.sort_order, l.id
        """,
        (allocation_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_allocation(conn: sqlite3.Connection, allocation_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM share_allocations WHERE id=?", (allocation_id,)).fetchone()
    if not row:
        return None
    allocation = dict(row)
    allocation["lines"] = _load_lines(conn, allocation_id)
    scheme = get_scheme(conn, allocation["scheme_id"])
    allocation["scheme"] = scheme
    return allocation


def list_allocations(
    conn: sqlite3.Connection, scheme_id: int | None = None, period: str | None = None
) -> list[dict]:
    q = (
        "SELECT a.*, s.name AS scheme_name "
        "FROM share_allocations a JOIN share_schemes s ON s.id=a.scheme_id WHERE 1=1"
    )
    args: list = []
    if scheme_id is not None:
        q += " AND a.scheme_id=?"
        args.append(scheme_id)
    if period:
        q += " AND a.period=?"
        args.append(period)
    q += " ORDER BY a.period DESC, a.id DESC"
    items = [dict(r) for r in conn.execute(q, args).fetchall()]
    for item in items:
        item["lines"] = _load_lines(conn, item["id"])
    return items


def insert_allocation(
    conn: sqlite3.Connection, scheme_id: int, period: str, result: dict
) -> int:
    """落一张分摊单，并为每个成员生成一条 source='shared' 的抄表。须在事务内调用。"""
    cur = conn.execute(
        """INSERT INTO share_allocations(scheme_id, period, master_kwh, status, created_at)
           VALUES (?,?,?, 'active', ?)""",
        (scheme_id, period, result["master_kwh"], _utcnow()),
    )
    allocation_id = int(cur.lastrowid)
    for idx, line in enumerate(result["lines"]):
        rc = conn.execute(
            """INSERT INTO readings(account_id, kwh, peak, period, source, share_allocation_id, superseded)
               VALUES (?,?,?,?, 'shared', ?, 0)""",
            (line["account_id"], line["allocated_kwh"], 0, period, allocation_id),
        )
        reading_id = int(rc.lastrowid)
        conn.execute(
            """INSERT INTO share_allocation_lines
                   (allocation_id, account_id, ratio, base_kwh, remainder_kwh,
                    allocated_kwh, reading_id, sort_order)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                allocation_id,
                line["account_id"],
                line["ratio"],
                line["base_kwh"],
                line["remainder_kwh"],
                line["allocated_kwh"],
                reading_id,
                idx,
            ),
        )
    return allocation_id


def supersede_active_allocation(
    conn: sqlite3.Connection, scheme_id: int, period: str, new_allocation_id: int
) -> int | None:
    """把同方案同账期的旧分摊单置为 superseded，并软标记其生成的抄表。返回旧单 id。"""
    old = find_active_allocation(conn, scheme_id, period)
    if not old:
        return None
    old_id = old["id"]
    conn.execute(
        "UPDATE share_allocations SET status='superseded', superseded_by_id=? WHERE id=?",
        (new_allocation_id, old_id),
    )
    conn.execute(
        "UPDATE readings SET superseded=1 WHERE source='shared' AND share_allocation_id=?",
        (old_id,),
    )
    return old_id
