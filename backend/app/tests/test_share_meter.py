import sqlite3

import pytest

from app.modules.share_meter.engine import split_kwh, validate_members
from app.modules.share_meter.schema import ensure_schema
from app.modules.share_meter.service import ShareError, ShareService

CORE_DDL = """
CREATE TABLE accounts(id INTEGER PRIMARY KEY, name TEXT, meter_no TEXT, note TEXT);
CREATE TABLE readings(id INTEGER PRIMARY KEY, account_id INTEGER, kwh REAL, peak INTEGER);
CREATE TABLE calc_runs(
    id INTEGER PRIMARY KEY, kind TEXT, account_id INTEGER,
    input_json TEXT, result_json TEXT, created_at TEXT);
"""

PLAN = {
    "name": "家属院合表",
    "master_account_id": 3,
    "remainder_account_id": 1,
    "members": [{"account_id": 1, "pct": 60}, {"account_id": 2, "pct": 40}],
}


def make_svc() -> ShareService:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(CORE_DDL)  # readings 用老结构，验证 ensure_schema 的迁移路径
    ensure_schema(conn)
    for i, name in enumerate(["张家", "李家", "总表户"], start=1):
        conn.execute("INSERT INTO accounts(id, name, meter_no) VALUES (?,?,?)", (i, name, f"M-{i}"))
    conn.commit()
    return ShareService(conn)


def add_master_reading(svc: ShareService, kwh: float, period: str = "2026-08"):
    svc._conn.execute(
        "INSERT INTO readings(account_id, kwh, peak, period) VALUES (3, ?, 0, ?)", (kwh, period)
    )
    svc._conn.commit()


# ---- 引擎 ----


def test_validate_members_ok():
    assert validate_members(PLAN["members"]) == []


def test_validate_members_sum_must_be_100():
    errs = validate_members([{"account_id": 1, "pct": 50}, {"account_id": 2, "pct": 40}])
    assert any("比例之和须恰好为 100" in e and "90" in e for e in errs)


def test_validate_members_no_duplicate():
    errs = validate_members([{"account_id": 1, "pct": 50}, {"account_id": 1, "pct": 50}])
    assert any("重复" in e for e in errs)


def test_validate_members_pct_range_and_type():
    assert validate_members([{"account_id": 1, "pct": 0}])
    assert validate_members([{"account_id": 1, "pct": 101}])
    assert validate_members([{"account_id": 1, "pct": 33.5}])
    assert validate_members([]) == ["成员户列表不能为空"]


def test_split_exact():
    r = split_kwh(1000, PLAN["members"], 1)
    assert [s["kwh"] for s in r["shares"]] == [600.0, 400.0]
    assert r["remainder_kwh"] == 0.0


def test_split_remainder_goes_to_owner():
    # 1.001 按 50/50 理论各 0.5005 → 0.5，余数 0.001 归归属成员
    r = split_kwh(1.001, [{"account_id": 1, "pct": 50}, {"account_id": 2, "pct": 50}], 2)
    by_id = {s["account_id"]: s["kwh"] for s in r["shares"]}
    assert by_id[1] == 0.5
    assert by_id[2] == 0.501
    assert r["remainder_kwh"] == 0.001
    assert round(sum(by_id.values()), 3) == 1.001


def test_split_sum_always_equals_master():
    members = [{"account_id": 1, "pct": 33}, {"account_id": 2, "pct": 33}, {"account_id": 3, "pct": 34}]
    for master in [0.001, 7.7, 100, 333.333, 9999.999]:
        r = split_kwh(master, members, 3)
        assert round(sum(s["kwh"] for s in r["shares"]), 3) == round(master, 3)


# ---- 服务：方案校验 ----


def test_create_plan_ok():
    svc = make_svc()
    plan = svc.create_plan(dict(PLAN))
    assert plan["id"] == 1
    assert plan["master_name"] == "总表户"
    assert [m["pct"] for m in plan["members"]] == [60, 40]


@pytest.mark.parametrize(
    "patch, keyword",
    [
        ({"name": " "}, "方案名称不能为空"),
        ({"master_account_id": 99}, "主表电量来源户不存在"),
        ({"members": [{"account_id": 1, "pct": 50}]}, "比例之和须恰好为 100"),
        (
            {"members": [{"account_id": 1, "pct": 60}, {"account_id": 1, "pct": 40}]},
            "重复",
        ),
        ({"remainder_account_id": 3}, "余数归属成员必须在成员户列表中"),
        (
            {"members": [{"account_id": 1, "pct": 60}, {"account_id": 99, "pct": 40}]},
            "成员户不存在",
        ),
    ],
)
def test_create_plan_validation_readable(patch, keyword):
    svc = make_svc()
    payload = {**PLAN, **patch}
    with pytest.raises(ShareError) as ei:
        svc.create_plan(payload)
    assert keyword in ei.value.message
    assert ei.value.status == 400


# ---- 服务：执行与重算 ----


def test_execute_splits_and_reconciles():
    svc = make_svc()
    plan = svc.create_plan(dict(PLAN))
    add_master_reading(svc, 1000)
    run = svc.execute(plan["id"], "2026-08")
    assert run["master_kwh"] == 1000.0
    got = {a["account_id"]: a["kwh"] for a in run["allocations"]}
    assert got == {1: 600.0, 2: 400.0}
    assert all(a["source"] == "share" and a["period"] == "2026-08" for a in run["allocations"])
    assert run["reconcile"]["balanced"] is True
    assert run["reconcile"]["allocated_sum"] == 1000.0


def test_execute_twice_needs_force():
    svc = make_svc()
    plan = svc.create_plan(dict(PLAN))
    add_master_reading(svc, 1000)
    svc.execute(plan["id"], "2026-08")
    with pytest.raises(ShareError) as ei:
        svc.execute(plan["id"], "2026-08")
    assert ei.value.status == 409
    assert "force" in ei.value.message


def test_execute_force_soft_marks_old_run():
    svc = make_svc()
    plan = svc.create_plan(dict(PLAN))
    add_master_reading(svc, 1000)
    first = svc.execute(plan["id"], "2026-08")
    second = svc.execute(plan["id"], "2026-08", force=True)
    # 旧抄表软标记而非物理删除
    old = svc._conn.execute(
        "SELECT superseded FROM readings WHERE share_run_id=?", (first["id"],)
    ).fetchall()
    assert old and all(r["superseded"] == 1 for r in old)
    old_run = svc._conn.execute(
        "SELECT status, superseded_by FROM share_runs WHERE id=?", (first["id"],)
    ).fetchone()
    assert old_run["status"] == "superseded"
    assert old_run["superseded_by"] == second["id"]
    # 新分摊有效且对账平衡
    assert second["reconcile"]["balanced"] is True
    active = svc._conn.execute(
        "SELECT COUNT(*) c FROM readings WHERE share_run_id=? AND superseded=0", (second["id"],)
    ).fetchone()
    assert active["c"] == 2


def test_execute_without_master_reading_fails():
    svc = make_svc()
    plan = svc.create_plan(dict(PLAN))
    with pytest.raises(ShareError) as ei:
        svc.execute(plan["id"], "2026-09")
    assert "无有效抄表电量" in ei.value.message


def test_execute_bad_period_format():
    svc = make_svc()
    plan = svc.create_plan(dict(PLAN))
    with pytest.raises(ShareError) as ei:
        svc.execute(plan["id"], "2026-13")
    assert "YYYY-MM" in ei.value.message


def test_execute_remainder_lands_on_owner():
    svc = make_svc()
    plan = svc.create_plan(
        {**PLAN, "remainder_account_id": 2, "members": [{"account_id": 1, "pct": 50}, {"account_id": 2, "pct": 50}]}
    )
    add_master_reading(svc, 1.001)
    run = svc.execute(plan["id"], "2026-08")
    got = {a["account_id"]: a["kwh"] for a in run["allocations"]}
    assert got == {1: 0.5, 2: 0.501}
    assert run["remainder_kwh"] == 0.001
    assert run["reconcile"]["balanced"] is True
