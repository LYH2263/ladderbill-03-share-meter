from fastapi import APIRouter

from app.services.billing_service import BillingService

router = APIRouter(tags=["readings"])


@router.get("/readings")
def list_readings():
    with BillingService() as svc:
        return {"items": svc.list_readings()}
