"""合表分摊业务服务：方案校验落库 + 按账期执行分摊 + 对账核验。"""
from app.db import connect
from app.modules.share_meter.engine import ShareValidationError, allocate, validate_ratios
from app.repositories import accounts as accounts_repo
from app.repositories import share as share_repo


class ShareConflictError(RuntimeError):
    """同一账期已分摊且未带 force，HTTP 层映射为 409。"""


class ShareService:
    def __init__(self):
        self._conn = connect()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ---------- 方案 ----------

    def list_accounts(self) -> list[dict]:
        return accounts_repo.list_all(self._conn)

    def list_schemes(self) -> list[dict]:
        return share_repo.list_schemes(self._conn)

    def get_scheme(self, scheme_id: int) -> dict | None:
        return share_repo.get_scheme(self._conn, scheme_id)

    def _validate_payload(self, master_account_id: int, remainder_account_id: int, members: list[dict]):
        # 户存在性
        if not accounts_repo.get(self._conn, master_account_id):
            raise ShareValidationError(f"主表电量来源户 {master_account_id} 不存在")
        account_ids = set()
        for m in members:
            account_ids.add(m["account_id"])
        for aid in sorted(account_ids):
            if not accounts_repo.get(self._conn, aid):
                raise ShareValidationError(f"成员户 {aid} 不存在")
        # 比例/去重/和为 100/余数归属（引擎统一校验，消息可读）
        validate_ratios(members, remainder_account_id)

    def create_scheme(self, payload) -> dict:
        members = [m.model_dump() for m in payload.members]
        self._validate_payload(payload.master_account_id, payload.remainder_account_id, members)
        scheme_id = share_repo.insert_scheme(
            self._conn,
            payload.name,
            payload.master_account_id,
            payload.remainder_account_id,
            members,
        )
        return share_repo.get_scheme(self._conn, scheme_id)

    def update_scheme(self, scheme_id: int, payload) -> dict:
        if not share_repo.get_scheme(self._conn, scheme_id):
            return None
        members = [m.model_dump() for m in payload.members]
        self._validate_payload(payload.master_account_id, payload.remainder_account_id, members)
        share_repo.update_scheme(
            self._conn,
            scheme_id,
            payload.name,
            payload.master_account_id,
            payload.remainder_account_id,
            members,
        )
        return share_repo.get_scheme(self._conn, scheme_id)

    # ---------- 分摊执行 ----------

    def list_allocations(self, scheme_id: int | None = None, period: str | None = None) -> list[dict]:
        return share_repo.list_allocations(self._conn, scheme_id, period)

    def get_allocation(self, allocation_id: int) -> dict | None:
        return share_repo.get_allocation(self._conn, allocation_id)

    def run_allocation(self, payload) -> dict:
        scheme = share_repo.get_scheme(self._conn, payload.scheme_id)
        if not scheme:
            raise ShareValidationError(f"分摊方案 {payload.scheme_id} 不存在")

        existing = share_repo.find_active_allocation(self._conn, payload.scheme_id, payload.period)
        if existing and not payload.force:
            raise ShareConflictError(
                f"方案「{scheme['name']}」在账期 {payload.period} 已分摊过"
                f"（分摊单 #{existing['id']}），重新计算请带 force=true"
            )

        members = [{"account_id": m["account_id"], "ratio": m["ratio"]} for m in scheme["members"]]
        result = allocate(payload.master_kwh, members, scheme["remainder_account_id"])

        # 重算：先在同一事务内软标记旧单与旧抄表，再落新单，最后一次提交
        old_id = None
        if existing and payload.force:
            old_id = share_repo.supersede_active_allocation(
                self._conn, payload.scheme_id, payload.period, -1
            )
        allocation_id = share_repo.insert_allocation(
            self._conn, payload.scheme_id, payload.period, result
        )
        if old_id is not None:
            self._conn.execute(
                "UPDATE share_allocations SET superseded_by_id=? WHERE id=?", (allocation_id, old_id)
            )
        self._conn.commit()

        allocation = share_repo.get_allocation(self._conn, allocation_id)
        allocation["superseded_allocation_id"] = old_id
        allocation["reconcile"] = self._reconcile(allocation_id, result["master_kwh"])
        return allocation

    def _reconcile(self, allocation_id: int, master_kwh: float) -> dict:
        """按落库后的成员抄表核验：生效成员分摊之和应等于主表电量。"""
        rows = self._conn.execute(
            """SELECT account_id, kwh FROM readings
                WHERE share_allocation_id=? AND superseded=0 AND source='shared'
                ORDER BY id""",
            (allocation_id,),
        ).fetchall()
        member_sum = round(sum(r["kwh"] for r in rows), 3)
        return {
            "master_kwh": round(float(master_kwh), 3),
            "member_sum": member_sum,
            "difference": round(member_sum - float(master_kwh), 3),
            "balanced": abs(member_sum - float(master_kwh)) < 1e-9,
        }
