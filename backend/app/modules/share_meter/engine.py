"""合表电量分摊纯计算：整数百分比例拆分，除不尽余数归指定成员。

本模块无数据库副作用，全部入参/出参均为普通 dict，便于单测。
电量统一保留 SCALE 位小数（与 engines.helpers.kwh_qty 一致，取 3 位）。
"""
import math

from app.engines.helpers import kwh_qty

SCALE = 3  # 电量小数位


class ShareValidationError(ValueError):
    """方案/分摊入参业务校验失败，消息为可读中文。"""


def validate_ratios(members: list[dict], remainder_account_id: int) -> None:
    """校验成员比例规则。

    members: [{"account_id": int, "ratio": int(百分比, 1..100)}]
    规则：成员不少于 2 户；比例为 1..100 的整数；成员不得重复；比例之和恰好 100；
    余数归属成员必须在成员列表内。
    """
    if not isinstance(members, list) or len(members) < 2:
        raise ShareValidationError("成员户至少需要 2 户")
    seen = set()
    total = 0
    for i, m in enumerate(members):
        aid = m.get("account_id")
        ratio = m.get("ratio")
        if not isinstance(aid, int) or isinstance(aid, bool):
            raise ShareValidationError(f"第 {i + 1} 个成员缺少有效的户号")
        if not isinstance(ratio, int) or isinstance(ratio, bool):
            raise ShareValidationError("分摊比例必须是整数百分比")
        if ratio < 1 or ratio > 100:
            raise ShareValidationError(f"户 {aid} 的比例 {ratio} 不合法，须在 1~100 之间")
        if aid in seen:
            raise ShareValidationError(f"成员户 {aid} 重复，同一户不能出现多次")
        seen.add(aid)
        total += ratio
    if total != 100:
        raise ShareValidationError(f"成员比例之和为 {total}，必须恰好等于 100")
    if not isinstance(remainder_account_id, int) or remainder_account_id not in seen:
        raise ShareValidationError("余数归属成员必须是成员列表中的一户")


def _floor_qty(x: float, scale: int = SCALE) -> float:
    factor = 10**scale
    return math.floor(x * factor + 1e-9) / factor  # 1e-9 抵消浮点误差


def allocate(master_kwh: float, members: list[dict], remainder_account_id: int) -> dict:
    """把主表电量按比例拆给各成员，除不尽的余数电量全部加到归属成员。

    返回：
      {
        "master_kwh": 量化后主表电量,
        "remainder_kwh": 总余数电量（≥0）,
        "allocated_sum": 成员分摊之和（应等于 master_kwh）,
        "lines": [{"account_id","ratio","base_kwh","remainder_kwh",
                   "allocated_kwh","is_remainder_owner"}, ...]
      }
    """
    try:
        master = float(master_kwh)
    except (TypeError, ValueError):
        raise ShareValidationError("主表电量必须是数字")
    if master < 0:
        raise ShareValidationError("主表电量不能为负数")
    master = kwh_qty(master)

    validate_ratios(members, remainder_account_id)

    # 先向下按位截断，保证余数是一个非负的小电量（< 成员数 × 0.001）
    bases = [(m, _floor_qty(master * m["ratio"] / 100.0)) for m in members]
    remainder = kwh_qty(master - sum(b for _, b in bases))

    lines = []
    for m, base in bases:
        is_owner = m["account_id"] == remainder_account_id
        piece = kwh_qty(remainder if is_owner else 0.0)
        lines.append(
            {
                "account_id": m["account_id"],
                "ratio": int(m["ratio"]),
                "base_kwh": base,
                "remainder_kwh": piece,
                "allocated_kwh": kwh_qty(base + piece),
                "is_remainder_owner": is_owner,
            }
        )
    allocated_sum = kwh_qty(sum(line["allocated_kwh"] for line in lines))
    return {
        "master_kwh": master,
        "remainder_kwh": remainder,
        "allocated_sum": allocated_sum,
        "balanced": abs(allocated_sum - master) < 1e-9,
        "lines": lines,
    }
