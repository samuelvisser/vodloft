from fastapi import FastAPI

from backend.api import api_router


def create_app() -> FastAPI:
    app = FastAPI(title="VodLoft API", version="0.1.0")
    app.include_router(api_router)

    @app.get("/api/health", tags=["system"])
    def health():
        return {"status": "ok", "application": "VodLoft"}

    return app


app = create_app()
