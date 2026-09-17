"""合表分摊服务/落库测试：校验、执行、对账、账期冲突与 force 重算软标记。"""
import pytest

from app.db import connect
from app.modules.share_meter.engine import ShareValidationError
from app.repositories import readings as readings_repo
from app.repositories import share as share_repo
from app.schemas.share import ShareAllocateIn, ShareSchemeIn
from app.services.share_service import ShareConflictError, ShareService


def _scheme_payload(name="测试合摊", master=1, remainder=1, pairs=((1, 40), (2, 30), (3, 30))):
    return ShareSchemeIn(
        name=name,
        master_account_id=master,
        remainder_account_id=remainder,
        members=[{"account_id": a, "ratio": r} for a, r in pairs],
    )


def _alloc_payload(scheme_id, period="2026-09", kwh=10.01, force=False):
    return ShareAllocateIn(scheme_id=scheme_id, period=period, master_kwh=kwh, force=force)


# ---------- 方案校验 ----------

def test_create_scheme_ok(fresh_db):
    with ShareService() as svc:
        scheme = svc.create_scheme(_scheme_payload())
    assert scheme["id"] > 0
    assert [m["account_id"] for m in scheme["members"]] == [1, 2, 3]
    assert [(m["account_id"], m["ratio"]) for m in scheme["members"]] == [(1, 40), (2, 30), (3, 30)]


def test_create_scheme_duplicate_member_rejected(fresh_db):
    with ShareService() as svc:
        with pytest.raises(ShareValidationError, match="重复"):
            svc.create_scheme(_scheme_payload(pairs=((1, 40), (1, 30), (2, 30))))


def test_create_scheme_ratio_sum_rejected(fresh_db):
    with ShareService() as svc:
        with pytest.raises(ShareValidationError, match="恰好等于 100"):
            svc.create_scheme(_scheme_payload(pairs=((1, 40), (2, 30), (3, 31))))


def test_create_scheme_remainder_owner_rejected(fresh_db):
    # 余数归属户 9 不在成员列表
    with ShareService() as svc:
        with pytest.raises(ShareValidationError, match="余数归属成员"):
            svc.create_scheme(_scheme_payload(remainder=9))


def test_create_scheme_nonexistent_account_rejected(fresh_db):
    with ShareService() as svc:
        with pytest.raises(ShareValidationError, match="不存在"):
            svc.create_scheme(_scheme_payload(master=999))


def test_update_scheme_replaces_members(fresh_db):
    with ShareService() as svc:
        created = svc.create_scheme(_scheme_payload())
        updated = svc.update_scheme(
            created["id"],
            _scheme_payload(name="改后方案", pairs=((1, 60), (2, 40)), remainder=2),
        )
    assert updated["name"] == "改后方案"
    assert [(m["account_id"], m["ratio"]) for m in updated["members"]] == [(1, 60), (2, 40)]
    assert updated["remainder_account_id"] == 2


def test_update_missing_scheme_returns_none(fresh_db):
    with ShareService() as svc:
        assert svc.update_scheme(9999, _scheme_payload()) is None


# ---------- 执行分摊 + 对账 + 来源标记 ----------

def test_run_allocation_creates_shared_readings_and_balances(fresh_db):
    with ShareService() as svc:
        scheme = svc.create_scheme(_scheme_payload(pairs=((1, 33), (2, 33), (3, 34))))
        allocation = svc.run_allocation(_alloc_payload(scheme["id"], kwh=10.01))

    assert allocation["period"] == "2026-09"
    # 余数 0.001 落到归属成员户1（33.03+0.001）
    assert {l["account_id"]: l["allocated_kwh"] for l in allocation["lines"]} == {
        1: 3.304,
        2: 3.303,
        3: 3.403,
    }
    # 对账：成员分摊之和 == 主表电量
    assert allocation["reconcile"] == {
        "master_kwh": 10.01,
        "member_sum": 10.01,
        "difference": 0.0,
        "balanced": True,
    }

    # 成员抄表带来源标记、账期与分摊单 id
    conn = connect()
    rows = readings_repo.search(conn, account_id=1, period="2026-09")
    shared = [r for r in rows if r["source"] == "shared"]
    assert len(shared) == 1
    assert shared[0]["kwh"] == 3.304
    assert shared[0]["share_allocation_id"] == allocation["id"]
    assert shared[0]["superseded"] == 0
    conn.close()


def test_run_allocation_unknown_scheme_rejected(fresh_db):
    with ShareService() as svc:
        with pytest.raises(ShareValidationError, match="不存在"):
            svc.run_allocation(_alloc_payload(9999))


def test_same_period_requires_force(fresh_db):
    with ShareService() as svc:
        scheme = svc.create_scheme(_scheme_payload())
        svc.run_allocation(_alloc_payload(scheme["id"], kwh=100.0))
        with pytest.raises(ShareConflictError, match="force"):
            svc.run_allocation(_alloc_payload(scheme["id"], kwh=120.0, force=False))


def test_force_recalculates_and_soft_marks_old_readings(fresh_db):
    with ShareService() as svc:
        scheme = svc.create_scheme(_scheme_payload())
        first = svc.run_allocation(_alloc_payload(scheme["id"], kwh=100.0))
        second = svc.run_allocation(_alloc_payload(scheme["id"], kwh=101.0, force=True))

    assert second["superseded_allocation_id"] == first["id"]

    conn = connect()
    # 旧分摊行仍物理存在，但被软标记作废；新分摊行生效
    old_rows = readings_repo.search(conn, period="2026-09")
    old_shared = [r for r in old_rows if r["share_allocation_id"] == first["id"]]
    new_shared = [r for r in old_rows if r["share_allocation_id"] == second["id"]]
    assert len(old_shared) == 3 and all(r["superseded"] == 1 for r in old_shared)
    assert len(new_shared) == 3 and all(r["superseded"] == 0 for r in new_shared)

    # 旧单状态为 superseded 且指向新单；同账期只有一张生效单
    old_alloc = share_repo.get_allocation(conn, first["id"])
    assert old_alloc["status"] == "superseded"
    assert old_alloc["superseded_by_id"] == second["id"]
    active = conn.execute(
        "SELECT COUNT(*) c FROM share_allocations WHERE scheme_id=? AND period=? AND status='active'",
        (scheme["id"], "2026-09"),
    ).fetchone()["c"]
    assert active == 1

    # 默认查询可看到作废痕迹；过滤后只剩新生效抄表
    live = readings_repo.search(conn, period="2026-09", include_superseded=False)
    assert {r["share_allocation_id"] for r in live if r["source"] == "shared"} == {second["id"]}

    # 重算后对账仍平衡
    assert second["reconcile"]["balanced"] is True
    conn.close()


def test_different_periods_coexist(fresh_db):
    with ShareService() as svc:
        scheme = svc.create_scheme(_scheme_payload())
        a1 = svc.run_allocation(_alloc_payload(scheme["id"], period="2026-08", kwh=100.0))
        a2 = svc.run_allocation(_alloc_payload(scheme["id"], period="2026-09", kwh=200.0))
    assert a1["id"] != a2["id"]
    with ShareService() as svc:
        items = svc.list_allocations(scheme_id=scheme["id"])
    assert {i["period"] for i in items} == {"2026-08", "2026-09"}
