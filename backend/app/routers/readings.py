from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.billing_service import BillingService

router = APIRouter(tags=["readings"])


class ReadingIn(BaseModel):
    account_id: int
    kwh: float = Field(ge=0)
    peak: bool = False
    period: str | None = None


@router.get("/readings")
def list_readings():
    with BillingService() as svc:
        return {"items": svc.list_readings()}


@router.post("/readings", status_code=201)
def create_reading(body: ReadingIn):
    with BillingService() as svc:
        row = svc.create_reading(body.account_id, body.kwh, body.peak, body.period)
        if row is None:
            raise HTTPException(404, f"户号不存在(id={body.account_id})")
        return row
