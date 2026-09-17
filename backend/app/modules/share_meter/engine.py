"""合表电量分摊引擎：按整数百分比拆分主表电量，除不尽的余数归指定成员。

纯函数，不碰数据库；校验返回可读中文错误列表，由服务层汇总抛出。
"""

from app.engines.helpers import kwh_qty


def validate_members(members: list[dict]) -> list[str]:
    """成员规则：至少 1 户、比例为 1-100 的整数、不得重复、之和恰好 100。"""
    errors: list[str] = []
    if not members:
        return ["成员户列表不能为空"]
    seen: set[int] = set()
    total = 0
    for m in members:
        aid = m.get("account_id")
        pct = m.get("pct")
        if isinstance(pct, bool) or not isinstance(pct, int) or not 1 <= pct <= 100:
            errors.append(f"成员户(id={aid})的比例须为 1-100 的整数，当前为 {pct!r}")
            continue
        if aid in seen:
            errors.append(f"成员户重复：id={aid}")
        seen.add(aid)
        total += pct
    if total != 100:
        errors.append(f"比例之和须恰好为 100，当前为 {total}")
    return errors


def split_kwh(master_kwh: float, members: list[dict], remainder_account_id: int) -> dict:
    """把主表电量按比例拆到成员。

    各成员先按比例取 3 位小数的理论值，归属成员实际量 = 主表总量 - 其他成员之和，
    因此成员分摊之和恒等于主表电量，余数（可正可负）全部落在归属成员头上。
    """
    total = kwh_qty(master_kwh)
    shares = [
        {"account_id": m["account_id"], "pct": m["pct"], "kwh": kwh_qty(total * m["pct"] / 100.0)}
        for m in members
    ]
    owner = next(s for s in shares if s["account_id"] == remainder_account_id)
    others_sum = kwh_qty(sum(s["kwh"] for s in shares if s["account_id"] != remainder_account_id))
    owner_actual = kwh_qty(total - others_sum)
    remainder = kwh_qty(owner_actual - owner["kwh"])
    owner["kwh"] = owner_actual
    return {"total_kwh": total, "remainder_kwh": remainder, "shares": shares}
