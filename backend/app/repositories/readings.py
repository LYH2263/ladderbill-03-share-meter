import sqlite3

_READING_COLUMNS = (
    "id, account_id, kwh, peak, period, source, share_allocation_id, superseded"
)


def list_all(conn: sqlite3.Connection, include_superseded: bool = True) -> list[dict]:
    q = f"SELECT {_READING_COLUMNS} FROM readings"
    if not include_superseded:
        q += " WHERE superseded=0"
    q += " ORDER BY id"
    return [dict(r) for r in conn.execute(q).fetchall()]


def for_account(conn: sqlite3.Connection, account_id: int) -> list[dict]:
    q = f"SELECT {_READING_COLUMNS} FROM readings WHERE account_id=? ORDER BY id"
    return [dict(r) for r in conn.execute(q, (account_id,)).fetchall()]


def search(
    conn: sqlite3.Connection,
    account_id: int | None = None,
    period: str | None = None,
    include_superseded: bool = True,
) -> list[dict]:
    """按户/账期过滤抄表，带分摊来源标记与作废软标记。"""
    where = []
    args: list = []
    if account_id is not None:
        where.append("account_id=?")
        args.append(account_id)
    if period:
        where.append("period=?")
        args.append(period)
    if not include_superseded:
        where.append("superseded=0")
    q = f"SELECT {_READING_COLUMNS} FROM readings"
    if where:
        q += " WHERE " + " AND ".join(where)
    q += " ORDER BY period DESC, id DESC"
    return [dict(r) for r in conn.execute(q, args).fetchall()]
