from fastapi import APIRouter
from .auth import auth_router
from .user_info import dw_user_info_router
from .catalog import dw_catalog_router
from .movies import dw_movie_router

router = APIRouter(prefix="/dailywire")

router.include_router(auth_router)
router.include_router(dw_user_info_router)
router.include_router(dw_catalog_router)
router.include_router(dw_movie_router)
