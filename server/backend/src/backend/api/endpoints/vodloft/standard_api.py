"""The design's public Source routes share the application's typed handlers."""
import subprocess

from fastapi import APIRouter, HTTPException, Request
from fastapi.routing import APIRoute

from backend.api.endpoints.vodloft.connections import router as connections
from backend.api.endpoints.vodloft.discovery import router as discovery
from backend.api.endpoints.vodloft.router import router as library
from backend.api.endpoints.vodloft.import_review import confirm_import, ConfirmImportResponse
from backend.source_manager.gateway import SourceInvocationError


class SourceAPIRoute(APIRoute):
    """Keep Source transport failures typed without changing authorization."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def typed_handler(request: Request):
            from backend.api.endpoints.vodloft.discovery import _failure
            try:
                return await handler(request)
            except HTTPException as exc:
                code = (exc.headers or {}).get('X-VodLoft-Source-Error')
                if code:
                    return _failure(SourceInvocationError(code, str(exc.detail)))
                raise
            except (SourceInvocationError, OSError, subprocess.TimeoutExpired) as exc:
                return _failure(exc)

        return typed_handler

router = APIRouter(tags=['Source contract'])

# Reuse the same request models, authorization and transport handlers. Aliases
# never introduce a second implementation of Source or library behavior.
for component in (library, discovery, connections):
    for route in component.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith('/vodloft/sources'):
            continue
        path = route.path.replace('/vodloft/sources/{source_id}', '/source/{source_id}', 1)
        path = path.replace('/vodloft/sources', '/sources', 1)
        router.add_api_route(path, route.endpoint, methods=sorted(route.methods),
            response_model=route.response_model, status_code=route.status_code,
            name=f'standard_{route.name}', operation_id=f'standard_{route.unique_id}',
            response_model_exclude_unset=route.response_model_exclude_unset,
            response_class=route.response_class, responses=route.responses, dependencies=route.dependencies,
            route_class_override=SourceAPIRoute)

router.add_api_route('/library/import', confirm_import, methods=['POST'],
    response_model=ConfirmImportResponse, name='standard_import', operation_id='standard_import')
