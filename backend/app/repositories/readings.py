import sqlite3


def list_all(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM readings ORDER BY id").fetchall()]


def for_account(conn: sqlite3.Connection, account_id: int) -> list[dict]:
    q = "SELECT * FROM readings WHERE account_id=? ORDER BY id"
    return [dict(r) for r in conn.execute(q, (account_id,)).fetchall()]


def insert(
    conn: sqlite3.Connection,
    account_id: int,
    kwh: float,
    peak: int = 0,
    period: str | None = None,
    source: str = "manual",
    share_run_id: int | None = None,
    commit: bool = True,
) -> int:
    cur = conn.execute(
        "INSERT INTO readings(account_id, kwh, peak, period, source, share_run_id)"
        " VALUES (?,?,?,?,?,?)",
        (account_id, kwh, peak, period, source, share_run_id),
    )
    if commit:
        conn.commit()
    return int(cur.lastrowid)
