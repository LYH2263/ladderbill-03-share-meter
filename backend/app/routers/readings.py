from fastapi import APIRouter

from app.services.billing_service import BillingService

router = APIRouter(tags=["readings"])


@router.get("/readings")
def list_readings(account_id: int | None = None, period: str | None = None,
                  include_superseded: bool = True):
    with BillingService() as svc:
        return {
            "items": svc.search_readings(
                account_id=account_id, period=period, include_superseded=include_superseded
            )
        }
