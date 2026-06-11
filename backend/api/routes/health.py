"""Health endpoint (E7-S1).

Liveness/readiness probe. Returns the fixed status body defined in
api-contracts.md §1; the BRD specifies a simple liveness contract (no dependency
fan-out) for this single-user demo, so the handler stays dependency-free and
fast.
"""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])

_SERVICE_NAME = "shopassistant-backend"
_VERSION = "1.0"


class HealthResponse(BaseModel):
    """The liveness body returned by ``GET /api/health`` (E7-S1 AC-1)."""

    status: str
    service: str
    version: str


@router.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Return a 200 status body confirming the service is live (AC-1)."""
    return HealthResponse(status="ok", service=_SERVICE_NAME, version=_VERSION)
