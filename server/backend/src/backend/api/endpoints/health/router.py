"""The health check and Prometheus metrics. Both answer without signing in, so
Docker and Prometheus can call them; neither says anything about what is in
the library beyond counts."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse

from config import get_settings

from backend.db import get_session
from backend.api.models.health import HealthRead
from backend.api.versions import HEALTH_PATH
from backend.services.health import check_health, metrics_text


# The health check stays outside every API version: Docker and uptime monitors only read its status code, so it
# keeps one address whatever the API's version is. The metrics are versioned with the rest of the API.
health_check_router = APIRouter(tags=["Health"])
router = APIRouter(tags=["Health"])


@health_check_router.get(HEALTH_PATH, response_model=HealthRead, responses={503: {"model": HealthRead}})
def health():
    """200 while the database answers and the scheduler runs, 503 otherwise."""
    with get_session() as session:
        result = check_health(session)
    body = HealthRead.model_validate(result).model_dump(mode="json", by_alias=True)
    return JSONResponse(body, status_code=200 if result.healthy else 503)


@router.get("/metrics", response_class=PlainTextResponse)
def metrics():
    if not get_settings().health.metrics_enabled:
        raise HTTPException(status_code=404, detail="Metrics are off. Turn them on with health.metricsEnabled in config.yml")
    with get_session() as session:
        body = metrics_text(session)
    return PlainTextResponse(body, media_type="text/plain; version=0.0.4; charset=utf-8")
