from typing import Protocol

from fastapi import HTTPException


class BillingProvider(Protocol):
    def create_checkout(self, organization_id: str, plan: str, idempotency_key: str) -> str: ...
    def verify_webhook(self, payload: bytes, signature: str) -> dict: ...
    def retrieve_subscription(self, organization_id: str) -> dict: ...
    def change_plan(self, organization_id: str, plan: str, idempotency_key: str) -> dict: ...
    def cancel(self, organization_id: str, idempotency_key: str) -> dict: ...
    def reconcile(self, organization_id: str) -> dict: ...


class DisabledBilling:
    def create_checkout(self, organization_id, plan, idempotency_key):
        raise HTTPException(
            503,
            "Paid plans are not enabled. A payment provider and commercial terms must be configured by the operator. Your free workspace remains available.",
        )

    def verify_webhook(self, payload, signature):
        raise HTTPException(503, "No payment provider configured; no billing changes accepted.")

    def retrieve_subscription(self, organization_id):
        return {"plan": "FREE", "status": "FREE", "provider": "disabled"}

    change_plan = create_checkout
    cancel = create_checkout
    reconcile = retrieve_subscription
