"""合表分摊 API：方案编辑、按账期执行、记录与对账。"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.modules.share_meter.service import ShareError, ShareService

router = APIRouter(prefix="/share", tags=["share_meter"])


class MemberIn(BaseModel):
    account_id: int
    pct: int


class PlanIn(BaseModel):
    name: str
    master_account_id: int
    remainder_account_id: int
    members: list[MemberIn] = Field(default_factory=list)


class ExecuteIn(BaseModel):
    plan_id: int
    period: str
    force: bool = False


def _call(fn, *args):
    try:
        with ShareService() as svc:
            return fn(svc, *args)
    except ShareError as e:
        raise HTTPException(e.status, e.message)


@router.get("/plans")
def list_plans():
    return {"items": _call(lambda s: s.list_plans())}


@router.post("/plans", status_code=201)
def create_plan(body: PlanIn):
    return _call(lambda s: s.create_plan(body.model_dump()))


@router.put("/plans/{plan_id}")
def update_plan(plan_id: int, body: PlanIn):
    return _call(lambda s: s.update_plan(plan_id, body.model_dump()))


@router.post("/execute")
def execute(body: ExecuteIn):
    return _call(lambda s: s.execute(body.plan_id, body.period, body.force))


@router.get("/runs")
def list_runs(plan_id: int | None = None):
    return {"items": _call(lambda s: s.list_runs(plan_id))}


@router.get("/runs/{run_id}")
def run_detail(run_id: int):
    return _call(lambda s: s.run_detail(run_id))
