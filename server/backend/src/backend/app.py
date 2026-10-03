from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager, contextmanager

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from sqlalchemy.exc import IntegrityError

from backend.api.errors import integrity_error_handler
from backend.utils.custom_index import CustomIndexNotReadyError
from backend.db import get_session
from backend.security.auth import is_authenticated
from config import get_settings
from config.network import NO_INTERNET_CONNECTION_MESSAGE, is_no_internet_error


logger = logging.getLogger(__name__)


@contextmanager
def db_session():
    s = get_session()
    try:
        yield s
    finally:
        s.close()


def _recover_download_filesystem(download_settings, scheduled_work_pause) -> None:
    """Reconcile crash leftovers without delaying API readiness.

    The caller acquires a scheduled-work pause before controller startup and
    hands that lease to this background thread. Other critical work may hold its
    own lease at the same time; normal work resumes only after the final lease is
    released.
    """
    from backend.services.vodloft_finalization import reconcile
    from backend.services.vodloft_retention import reconcile as reconcile_retention
    try:
        reconcile()
        reconcile_retention()
    except Exception:
        logger.exception("Download filesystem recovery failed")
    finally:
        scheduled_work_pause.release()


@asynccontextmanager
async def application_lifespan(app: FastAPI):
    """Own the background controller for exactly one ASGI app lifespan."""
    import controller
    from task_manager.scheduler.scheduler import (
        pause_scheduled_work,
        start_scheduler,
    )

    settings = get_settings()

    # Acquire the filesystem-recovery lease before controller startup so no
    # normal job can slip through while durable work is being restored. Critical
    # tasks (for example background migrations) use their own scheduler lane and
    # may start while this lease is active.
    start_scheduler()
    filesystem_pause = pause_scheduled_work(
        "download filesystem recovery",
        owner_key="startup-download-filesystem-recovery",
    )

    started = False
    recovery_started = False
    automation_stop = threading.Event()
    try:
        controller.start_controller()
        started = True
        from backend.services.vodloft_finalization import reconcile as reconcile_vodloft_files
        reconcile_vodloft_files()
        from backend.api.endpoints.vodloft.router import recover_acquisition_jobs
        recover_acquisition_jobs()

        def collection_automation_loop():
            from backend.api.endpoints.vodloft.automation import refresh_due_collections
            from backend.source_manager.runtime import check_updates
            from backend.api.endpoints.vodloft.feeds import prepare_subscribed_feeds
            from backend.api.endpoints.vodloft.integrations import reconcile_exports, reconcile_feed_deliveries
            from backend.api.endpoints.vodloft.playback import expire_sessions
            from backend.services.vodloft_retention import reconcile as reconcile_retention
            from backend.api.endpoints.vodloft.router import recover_acquisition_jobs, retry_due_acquisition_jobs
            from task_manager.scheduler.scheduler import scheduled_work_is_paused
            while not automation_stop.wait(15):
                if not scheduled_work_is_paused():
                    automatic = (check_updates, refresh_due_collections, prepare_subscribed_feeds, retry_due_acquisition_jobs) if get_settings().scheduler.enabled else ()
                    for sweep in (*automatic, recover_acquisition_jobs, reconcile_exports,
                                  reconcile_feed_deliveries, expire_sessions, reconcile_retention):
                        try:
                            sweep()
                        except Exception:
                            logger.exception("Automatic sweep %s failed", sweep.__name__)
                if automation_stop.wait(45):
                    break

        threading.Thread(target=collection_automation_loop, name="vodloft-automation",
                         daemon=True).start()

        recovery_thread = threading.Thread(
            target=_recover_download_filesystem,
            args=(settings.download_settings, filesystem_pause),
            name="vodloft-startup-download-recovery",
            daemon=True,
        )
        recovery_thread.start()
        recovery_started = True
        yield
    finally:
        automation_stop.set()
        if not recovery_started:
            filesystem_pause.release()
        if started:
            controller.stop_controller()


async def _network_aware_http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
):
    """Normalize HTTP errors whose underlying cause is a local internet outage."""
    if is_no_internet_error(exc):
        logger.warning(NO_INTERNET_CONNECTION_MESSAGE)
        return JSONResponse(
            {"detail": NO_INTERNET_CONNECTION_MESSAGE},
            status_code=503,
        )
    return await http_exception_handler(request, exc)


def create_app() -> FastAPI:
    app = FastAPI(
        title="VodLoft API",
        summary="Local web media library API",
        version=get_settings().app_version,
        lifespan=application_lifespan,
    )

    # Allow the React dev server to call the API during development (with credentials)
    # Configure allowed origins via WL_CORS_ORIGINS (comma-separated). Defaults include common Vite dev hosts.
    import os
    origins_env = os.environ.get("WL_CORS_ORIGINS", "").strip()
    if origins_env:
        allow_origins = [o.strip() for o in origins_env.split(",") if o.strip()]
    else:
        allow_origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Exception handlers
    app.add_exception_handler(IntegrityError, integrity_error_handler)
    app.add_exception_handler(StarletteHTTPException, _network_aware_http_exception_handler)

    @app.exception_handler(CustomIndexNotReadyError)
    async def _custom_index_waiting(_request: Request, error: CustomIndexNotReadyError):
        if error.repair_show_id is not None and error.repair_profile_id is not None:
            from backend.services.custom_indexes import request_custom_index_reconciliation
            with db_session() as session:
                request_custom_index_reconciliation(
                    session, show_id=error.repair_show_id,
                    local_media_profile_id=error.repair_profile_id,
                )
                session.commit()
        return JSONResponse({"detail": str(error)}, status_code=409)

    # Auth middleware to protect all API endpoints except /api/auth/*
    @app.middleware("http")
    async def _auth_guard(request: Request, call_next):
        try:
            # Allow CORS preflight requests to pass through without auth
            if request.method == "OPTIONS":
                return await call_next(request)

            path = request.url.path
            # Protect all /api/* except public auth endpoints
            is_api = path.startswith("/api/")
            is_public_auth = path.startswith("/api/auth")
            is_public_config = path == "/api/config/public"
            if is_api and not (is_public_auth or is_public_config):
                if not is_authenticated(request):
                    return JSONResponse({"detail": "Not authenticated"}, status_code=401)
                from backend.security.permissions import principal, allowed_api
                request.state.principal = principal(request)
                if not allowed_api(request.state.principal, request.method, path):
                    return JSONResponse({"detail": "This action requires library or administrator permission"}, status_code=403)
            return await call_next(request)
        except Exception as exc:
            # External HTTP clients use several libraries. Normalize only strong
            # local-connectivity signals here so ordinary upstream/API failures keep
            # their existing diagnostics and status handling.
            if not is_no_internet_error(exc):
                raise
            logger.warning(NO_INTERNET_CONNECTION_MESSAGE)
            return JSONResponse(
                {"detail": NO_INTERNET_CONNECTION_MESSAGE},
                status_code=503,
            )

    # Import routers lazily to avoid circular imports during app module import
    from backend.api.endpoints.onboarding.router import router as onboarding_router
    from backend.api.endpoints.operations.router import router as operation_router
    from backend.api.endpoints.puller.router import router as puller_router
    from backend.api.endpoints.settings.router import router as setting_router
    from backend.api.endpoints.config.router import router as config_router
    from backend.api.endpoints.meta_router import router as meta_router
    from backend.api.endpoints.auth.router import router as auth_router
    from backend.api.endpoints.vodloft import router as vodloft_router
    from backend.api.endpoints.vodloft.feeds import api_router as vodloft_feeds_api, public_router as vodloft_feeds_public
    from backend.api.endpoints.vodloft.profiles import router as vodloft_profiles_router
    from backend.api.endpoints.vodloft.automation import router as vodloft_automation_router
    from backend.api.endpoints.vodloft.integrations import router as vodloft_integrations_router
    from backend.api.endpoints.vodloft.connections import router as vodloft_connections_router
    from backend.api.endpoints.vodloft.playback import router as vodloft_playback_router
    from backend.api.endpoints.vodloft.requests import router as vodloft_requests_router

    # Public auth endpoints
    app.include_router(auth_router, prefix="/api")
    app.include_router(vodloft_router, prefix="/api")
    app.include_router(vodloft_feeds_api, prefix="/api")
    app.include_router(vodloft_profiles_router, prefix="/api")
    app.include_router(vodloft_automation_router, prefix="/api")
    app.include_router(vodloft_integrations_router, prefix="/api")
    app.include_router(vodloft_connections_router, prefix="/api")
    app.include_router(vodloft_playback_router, prefix="/api")
    app.include_router(vodloft_requests_router, prefix="/api")
    app.include_router(vodloft_feeds_public)

    # WireLoft's shared infrastructure remains; all media workflows use the
    # normalized library and the Source gateway.
    for shared_router in (onboarding_router, operation_router, puller_router,
                          setting_router, meta_router, config_router):
        app.include_router(shared_router, prefix="/api")

    return app
