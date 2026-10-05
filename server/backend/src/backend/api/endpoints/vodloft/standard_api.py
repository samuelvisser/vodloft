"""The design's public Source routes share the application's typed handlers."""
from fastapi import APIRouter
from fastapi.routing import APIRoute

from backend.api.endpoints.vodloft.connections import router as connections
from backend.api.endpoints.vodloft.discovery import router as discovery
from backend.api.endpoints.vodloft.router import router as library
from backend.api.endpoints.vodloft.import_review import confirm_import, ConfirmImportResponse

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
            response_class=route.response_class, responses=route.responses, dependencies=route.dependencies)

router.add_api_route('/library/import', confirm_import, methods=['POST'],
    response_model=ConfirmImportResponse, name='standard_import', operation_id='standard_import')
