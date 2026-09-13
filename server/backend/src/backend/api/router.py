from fastapi import APIRouter

from .auth import router as auth_router
from .library import router as library_router
from .media_downloads import router as media_downloads_router
from .profiles import router as profiles_router
from .rss import router as rss_router
from .settings import router as settings_router
from .tasks import router as tasks_router

api_router = APIRouter(prefix="/api")
api_router.include_router(auth_router)
api_router.include_router(library_router)
api_router.include_router(media_downloads_router)
api_router.include_router(profiles_router)
api_router.include_router(rss_router)
api_router.include_router(settings_router)
api_router.include_router(tasks_router)
