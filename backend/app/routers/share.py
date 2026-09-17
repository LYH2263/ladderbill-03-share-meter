from fastapi import APIRouter, HTTPException, Query

from app.modules.share_meter.engine import ShareValidationError
from app.schemas.share import ShareAllocateIn, ShareSchemeIn
from app.services.share_service import ShareConflictError, ShareService

router = APIRouter(tags=["share_meter"])


# ---------- 分摊方案 ----------

@router.get("/share/schemes")
def list_schemes():
    with ShareService() as svc:
        return {"items": svc.list_schemes()}


@router.post("/share/schemes", status_code=201)
def create_scheme(body: ShareSchemeIn):
    with ShareService() as svc:
        try:
            scheme = svc.create_scheme(body)
        except ShareValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return scheme


@router.get("/share/schemes/{scheme_id}")
def get_scheme(scheme_id: int):
    with ShareService() as svc:
        scheme = svc.get_scheme(scheme_id)
        if not scheme:
            raise HTTPException(status_code=404, detail=f"分摊方案 {scheme_id} 不存在")
        return scheme


@router.put("/share/schemes/{scheme_id}")
def update_scheme(scheme_id: int, body: ShareSchemeIn):
    with ShareService() as svc:
        try:
            scheme = svc.update_scheme(scheme_id, body)
        except ShareValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if scheme is None:
            raise HTTPException(status_code=404, detail=f"分摊方案 {scheme_id} 不存在")
        return scheme


# ---------- 按账期执行 / 查看 ----------

@router.get("/share/allocations")
def list_allocations(scheme_id: int | None = None, period: str | None = None):
    with ShareService() as svc:
        return {"items": svc.list_allocations(scheme_id, period)}


@router.get("/share/allocations/{allocation_id}")
def get_allocation(allocation_id: int):
    with ShareService() as svc:
        allocation = svc.get_allocation(allocation_id)
        if not allocation:
            raise HTTPException(status_code=404, detail=f"分摊单 {allocation_id} 不存在")
        return allocation


@router.post("/share/allocations/run", status_code=201)
def run_allocation(body: ShareAllocateIn):
    with ShareService() as svc:
        try:
            return svc.run_allocation(body)
        except ShareValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except ShareConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
