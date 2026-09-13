from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.api import api_router
from controller import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(_: FastAPI):
    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()


def create_app() -> FastAPI:
    app = FastAPI(title="VodLoft API", version="0.1.0", lifespan=lifespan)
    app.include_router(api_router)

    @app.get("/api/health", tags=["system"])
    def health():
        return {"status": "ok", "application": "VodLoft"}

    return app


app = create_app()
