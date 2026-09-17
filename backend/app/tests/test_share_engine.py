"""合表分摊纯引擎测试：整数比例 + 除不尽余数归属。"""
import pytest

from app.modules.share_meter.engine import ShareValidationError, allocate, validate_ratios


def test_exact_division_no_remainder():
    # 100 度按 40/30/30，整除无余数
    r = allocate(100, _members([(1, 40), (2, 30), (3, 30)]), 1)
    assert r["balanced"] is True
    assert [l["allocated_kwh"] for l in r["lines"]] == [40.0, 30.0, 30.0]
    assert r["remainder_kwh"] == 0.0
    assert sum(l["allocated_kwh"] for l in r["lines"]) == 100.0


def test_remainder_goes_to_owner():
    # 10.01 度按 33/33/34：base = floor 到 3 位 = 3.303 / 3.303 / 3.403，
    # 合计 10.009，余数 0.001 落到归属成员（户1）
    r = allocate(10.01, _members([(1, 33), (2, 33), (3, 34)]), 1)
    owner = next(l for l in r["lines"] if l["is_remainder_owner"])
    assert owner["account_id"] == 1
    assert r["remainder_kwh"] == 0.001
    assert [l["allocated_kwh"] for l in r["lines"]] == [3.304, 3.303, 3.403]
    assert r["allocated_sum"] == 10.01
    assert r["balanced"] is True


def test_remainder_owner_is_different_member():
    # 归属成员为户3：余数由户3吃进
    r = allocate(10.01, _members([(1, 33), (2, 33), (3, 34)]), 3)
    assert [l["allocated_kwh"] for l in r["lines"]] == [3.303, 3.303, 3.404]
    assert r["allocated_sum"] == 10.01


def test_exact_case_no_accumulated_remainder():
    # 250 度 33/33/34：82.5/82.5/85.0 在 3 位下整除，余数为 0
    r = allocate(250, _members([(1, 33), (2, 33), (3, 34)]), 1)
    assert r["allocated_sum"] == 250.0
    assert r["remainder_kwh"] == 0.0
    assert [l["allocated_kwh"] for l in r["lines"]] == [82.5, 82.5, 85.0]


def test_zero_master_kwh():
    r = allocate(0, _members([(1, 50), (2, 50)]), 2)
    assert [l["allocated_kwh"] for l in r["lines"]] == [0.0, 0.0]
    assert r["balanced"] is True
    assert r["remainder_kwh"] == 0.0


def test_duplicate_member_rejected():
    with pytest.raises(ShareValidationError, match="重复"):
        validate_ratios(_members([(1, 40), (1, 60)]), 1)


def test_ratio_sum_not_100():
    with pytest.raises(ShareValidationError, match="恰好等于 100"):
        validate_ratios(_members([(1, 40), (2, 59)]), 1)


def test_remainder_owner_not_in_members():
    with pytest.raises(ShareValidationError, match="余数归属成员"):
        validate_ratios(_members([(1, 40), (2, 60)]), 3)


def test_ratio_out_of_range():
    with pytest.raises(ShareValidationError, match="1~100"):
        validate_ratios(_members([(1, 0), (2, 100)]), 1)


def test_fewer_than_two_members():
    with pytest.raises(ShareValidationError, match="至少需要 2 户"):
        validate_ratios([{"account_id": 1, "ratio": 100}], 1)


def test_master_kwh_negative():
    with pytest.raises(ShareValidationError, match="不能为负"):
        allocate(-1, _members([(1, 50), (2, 50)]), 1)


def _members(pairs):
    return [{"account_id": aid, "ratio": ratio} for aid, ratio in pairs]
