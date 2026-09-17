"""合表分摊服务：方案管理、按账期执行、重算软标记与对账。"""

import re
import sqlite3
from datetime import datetime, timezone

from app.db import connect
from app.engines.helpers import kwh_qty
from app.modules.share_meter.engine import split_kwh, validate_members
from app.modules.share_meter.schema import ensure_schema
from app.repositories import accounts as accounts_repo
from app.repositories import readings as readings_repo
from app.repositories import runs as runs_repo

PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class ShareError(Exception):
    """可读的业务错误，路由层转成对应 HTTP 状态码。"""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ShareService:
    def __init__(self, conn: sqlite3.Connection | None = None):
        self._conn = conn or connect()
        self._own = conn is None
        ensure_schema(self._conn)

    def close(self):
        if self._own:
            self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ---- 方案 ----

    def list_plans(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM share_plans ORDER BY id").fetchall()
        return [self._plan_out(dict(r)) for r in rows]

    def get_plan(self, plan_id: int) -> dict:
        row = self._conn.execute(
            "SELECT * FROM share_plans WHERE id=?", (plan_id,)
        ).fetchone()
        if not row:
            raise ShareError(f"分摊方案不存在(id={plan_id})", 404)
        return self._plan_out(dict(row))

    def create_plan(self, payload: dict) -> dict:
        self._validate_payload(payload)
        now = _now()
        cur = self._conn.execute(
            "INSERT INTO share_plans(name, master_account_id, remainder_account_id, created_at, updated_at)"
            " VALUES (?,?,?,?,?)",
            (payload["name"].strip(), payload["master_account_id"], payload["remainder_account_id"], now, now),
        )
        plan_id = int(cur.lastrowid)
        self._replace_members(plan_id, payload["members"])
        self._conn.commit()
        return self.get_plan(plan_id)

    def update_plan(self, plan_id: int, payload: dict) -> dict:
        self.get_plan(plan_id)  # 404 前置
        self._validate_payload(payload)
        self._conn.execute(
            "UPDATE share_plans SET name=?, master_account_id=?, remainder_account_id=?, updated_at=? WHERE id=?",
            (payload["name"].strip(), payload["master_account_id"], payload["remainder_account_id"], _now(), plan_id),
        )
        self._conn.execute("DELETE FROM share_plan_members WHERE plan_id=?", (plan_id,))
        self._replace_members(plan_id, payload["members"])
        self._conn.commit()
        return self.get_plan(plan_id)

    def _replace_members(self, plan_id: int, members: list[dict]) -> None:
        self._conn.executemany(
            "INSERT INTO share_plan_members(plan_id, account_id, pct) VALUES (?,?,?)",
            [(plan_id, m["account_id"], m["pct"]) for m in members],
        )

    def _validate_payload(self, payload: dict) -> None:
        errors: list[str] = []
        name = (payload.get("name") or "").strip()
        if not name:
            errors.append("方案名称不能为空")
        master_id = payload.get("master_account_id")
        if not accounts_repo.get(self._conn, master_id):
            errors.append(f"主表电量来源户不存在(id={master_id})")
        members = payload.get("members") or []
        errors.extend(validate_members(members))
        for m in members:
            if not accounts_repo.get(self._conn, m.get("account_id")):
                errors.append(f"成员户不存在(id={m.get('account_id')})")
        remainder_id = payload.get("remainder_account_id")
        if remainder_id not in {m.get("account_id") for m in members}:
            errors.append("余数归属成员必须在成员户列表中")
        if errors:
            raise ShareError("；".join(errors))

    def _plan_out(self, plan: dict) -> dict:
        members = [
            dict(r)
            for r in self._conn.execute(
                "SELECT account_id, pct FROM share_plan_members WHERE plan_id=? ORDER BY id",
                (plan["id"],),
            ).fetchall()
        ]
        for m in members:
            acc = accounts_repo.get(self._conn, m["account_id"])
            m["name"] = acc["name"] if acc else f"#{m['account_id']}"
        master = accounts_repo.get(self._conn, plan["master_account_id"])
        plan["master_name"] = master["name"] if master else f"#{plan['master_account_id']}"
        plan["members"] = members
        return plan

    # ---- 执行分摊 ----

    def execute(self, plan_id: int, period: str, force: bool = False) -> dict:
        plan = self.get_plan(plan_id)
        if not PERIOD_RE.match(period or ""):
            raise ShareError(f"账期格式应为 YYYY-MM，当前为 {period!r}")
        existing = self._conn.execute(
            "SELECT * FROM share_runs WHERE plan_id=? AND period=? AND status='active'",
            (plan_id, period),
        ).fetchone()
        if existing and not force:
            raise ShareError(
                f"账期 {period} 已分摊（记录#{existing['id']}），如需重算请勾选 force", 409
            )
        master_kwh = self._master_kwh(plan["master_account_id"], period)
        if master_kwh is None:
            raise ShareError(
                f"主表户【{plan['master_name']}】在账期 {period} 无有效抄表电量，请先录入"
            )
        split = split_kwh(master_kwh, plan["members"], plan["remainder_account_id"])
        try:
            if existing:
                # 软标记旧分摊：抄表置 superseded、旧记录置 superseded，不物理删除
                self._conn.execute(
                    "UPDATE readings SET superseded=1 WHERE share_run_id=?", (existing["id"],)
                )
                self._conn.execute(
                    "UPDATE share_runs SET status='superseded' WHERE id=?", (existing["id"],)
                )
            run_id = self._insert_run(plan, period, split)
            for share in split["shares"]:
                readings_repo.insert(
                    self._conn,
                    account_id=share["account_id"],
                    kwh=share["kwh"],
                    peak=0,
                    period=period,
                    source="share",
                    share_run_id=run_id,
                    commit=False,
                )
            if existing:
                self._conn.execute(
                    "UPDATE share_runs SET superseded_by=? WHERE id=?", (run_id, existing["id"])
                )
            runs_repo.insert(
                self._conn,
                "share",
                {"plan_id": plan_id, "period": period, "force": force},
                {"run_id": run_id, "master_kwh": split["total_kwh"], "remainder_kwh": split["remainder_kwh"]},
                None,
            )  # runs_repo.insert 内部 commit，整体落库
        except Exception:
            self._conn.rollback()
            raise
        return self.run_detail(run_id)

    def _master_kwh(self, master_account_id: int, period: str) -> float | None:
        row = self._conn.execute(
            "SELECT SUM(kwh) AS total, COUNT(*) AS n FROM readings"
            " WHERE account_id=? AND period=? AND superseded=0 AND source='manual'",
            (master_account_id, period),
        ).fetchone()
        if not row or row["n"] == 0:
            return None
        return kwh_qty(row["total"])

    def _insert_run(self, plan: dict, period: str, split: dict) -> int:
        allocated = kwh_qty(sum(s["kwh"] for s in split["shares"]))
        cur = self._conn.execute(
            "INSERT INTO share_runs(plan_id, period, master_kwh, allocated_kwh, remainder_kwh,"
            " remainder_account_id, status, created_at) VALUES (?,?,?,?,?,?, 'active', ?)",
            (
                plan["id"],
                period,
                split["total_kwh"],
                allocated,
                split["remainder_kwh"],
                plan["remainder_account_id"],
                _now(),
            ),
        )
        return int(cur.lastrowid)

    # ---- 记录与对账 ----

    def list_runs(self, plan_id: int | None = None) -> list[dict]:
        q = (
            "SELECT r.*, p.name AS plan_name FROM share_runs r"
            " JOIN share_plans p ON p.id = r.plan_id"
        )
        args: tuple = ()
        if plan_id is not None:
            q += " WHERE r.plan_id=?"
            args = (plan_id,)
        q += " ORDER BY r.id DESC"
        return [dict(r) for r in self._conn.execute(q, args).fetchall()]

    def run_detail(self, run_id: int) -> dict:
        row = self._conn.execute(
            "SELECT r.*, p.name AS plan_name FROM share_runs r"
            " JOIN share_plans p ON p.id = r.plan_id WHERE r.id=?",
            (run_id,),
        ).fetchone()
        if not row:
            raise ShareError(f"分摊记录不存在(id={run_id})", 404)
        run = dict(row)
        allocations = [
            dict(r)
            for r in self._conn.execute(
                "SELECT r.id AS reading_id, r.account_id, a.name, m.pct, r.kwh, r.period,"
                " r.source, r.share_run_id, r.superseded"
                " FROM readings r"
                " JOIN accounts a ON a.id = r.account_id"
                " LEFT JOIN share_plan_members m"
                "   ON m.plan_id = ? AND m.account_id = r.account_id"
                " WHERE r.share_run_id=? ORDER BY r.id",
                (run["plan_id"], run_id),
            ).fetchall()
        ]
        run["allocations"] = allocations
        run["reconcile"] = self._reconcile(run, allocations)
        return run

    @staticmethod
    def _reconcile(run: dict, allocations: list[dict]) -> dict:
        allocated_sum = kwh_qty(sum(a["kwh"] for a in allocations))
        diff = kwh_qty(run["master_kwh"] - allocated_sum)
        return {
            "master_kwh": run["master_kwh"],
            "allocated_sum": allocated_sum,
            "remainder_kwh": run["remainder_kwh"],
            "remainder_account_id": run["remainder_account_id"],
            "diff": diff,
            "balanced": abs(diff) < 1e-6,
        }
