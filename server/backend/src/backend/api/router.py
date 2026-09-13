from fastapi import APIRouter

from .library import router as library_router
from .media_downloads import router as media_downloads_router
from .profiles import router as profiles_router
from .tasks import router as tasks_router

api_router = APIRouter(prefix="/api")
api_router.include_router(library_router)
api_router.include_router(media_downloads_router)
api_router.include_router(profiles_router)
api_router.include_router(tasks_router)
