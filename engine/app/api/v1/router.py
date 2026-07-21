from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints.health import router as health_router
from app.api.v1.endpoints.check_domain import router as domain_router
from app.api.v1.endpoints.check_email import router as email_router
from app.api.v1.endpoints.check_ip import router as ip_router


router = APIRouter()
router.include_router(health_router)
router.include_router(ip_router, prefix="/v1")
router.include_router(domain_router, prefix="/v1")
router.include_router(email_router, prefix="/v1")
