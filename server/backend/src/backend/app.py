from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from task_manager import start_task_system, stop_task_system

from backend.api import api_router
from backend.db import SessionLocal
from backend.security import SESSION_COOKIE, authenticated, ensure_application_settings


@asynccontextmanager
async def lifespan(_: FastAPI):
    start_task_system()
    try:
        yield
    finally:
        stop_task_system()


def create_app() -> FastAPI:
    app = FastAPI(title="VodLoft API", version="0.2.0", lifespan=lifespan)
    app.include_router(api_router)

    @app.middleware("http")
    async def admin_auth(request: Request, call_next):
        path = request.url.path
        public = (
            path == "/api/health"
            or path.startswith("/api/auth/")
            or path.startswith("/api/rss/")
        )
        if path.startswith("/api/") and not public:
            with SessionLocal() as session:
                settings = ensure_application_settings(session)
                if not authenticated(request.cookies.get(SESSION_COOKIE), settings):
                    return JSONResponse({"detail": "Authentication required"}, status_code=401)
        return await call_next(request)

    @app.get("/api/health", tags=["system"])
    def health():
        return {"status": "ok", "application": "VodLoft"}

    return app


app = create_app()
