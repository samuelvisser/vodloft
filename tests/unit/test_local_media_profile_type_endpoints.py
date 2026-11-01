from __future__ import annotations


def _methods(router, path: str) -> set[str]:
    return {
        method
        for route in router.routes
        if getattr(route, "path", None) == path
        for method in route.methods
    }


def test_local_media_profile_mutations_are_type_specific() -> None:
    from backend.api.endpoints.local_media_profiles.router import router as base_router
    from backend.api.endpoints.movie_local_media_profiles.router import (
        router as movie_router,
    )
    from backend.api.endpoints.collection_local_media_profiles.router import (
        router as collection_router,
    )

    assert _methods(base_router, "/local-media-profiles") == {"GET"}
    assert _methods(
        base_router,
        "/local-media-profiles/{local_media_profile_slug}",
    ) == {"GET"}

    assert {"GET", "POST"} <= _methods(
        collection_router,
        "/collection-local-media-profiles",
    )
    assert {"GET", "PATCH", "DELETE"} <= _methods(
        collection_router,
        "/collection-local-media-profiles/{local_media_profile_slug}",
    )
    assert _methods(
        collection_router,
        "/collection-local-media-profiles/{local_media_profile_slug}/rename-files",
    ) == {"POST"}

    assert {"GET", "POST"} <= _methods(
        movie_router,
        "/movie-local-media-profiles",
    )
    assert {"GET", "PATCH", "DELETE"} <= _methods(
        movie_router,
        "/movie-local-media-profiles/{local_media_profile_slug}",
    )


def test_local_media_profile_request_models_only_expose_their_own_fields() -> None:
    from backend.api.models.movie_local_media_profile import (
        MovieLocalMediaProfileAPICreate,
    )
    from backend.api.models.collection_local_media_profile import (
        CollectionLocalMediaProfileAPICreate,
    )

    assert "collection_scope" in CollectionLocalMediaProfileAPICreate.model_fields
    assert "collection_scope" not in MovieLocalMediaProfileAPICreate.model_fields
