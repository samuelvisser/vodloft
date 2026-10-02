"""WireLoft record compatibility over the separately executed Daily Wire Source.

The inherited screens and jobs expect Daily Wire record classes. This adapter
rehydrates their values after the Source worker performs the network request;
no upstream Daily Wire client is instantiated in the application process.
"""

from dataclasses import asdict, is_dataclass

from dailywire_api.dw_api.client import (
    ByNextPage, ByPodcastSeason, ByShowSeason, EpisodesPaginatedResult,
    MiddlewareAPIError,
)
from dailywire_api.records import (
    DwCatalogRecord, DwEpisodeDetailRecord, DwEpisodeRecord,
    DwMovieDetailRecord, DwMovieExtraDetailRecord, DwMovieRecord,
    DwShowRecord, DwUserInfo,
)

from backend.source_manager.gateway import SourceGateway, SourceInvocationError


_RESULTS = {
    "get_show_page": DwShowRecord,
    "get_catalog": DwCatalogRecord,
    "get_movie_playback": DwMovieDetailRecord,
    "get_movie_extra_playback": DwMovieExtraDetailRecord,
    "get_user_info": DwUserInfo,
    "get_episode_details": DwEpisodeDetailRecord,
    "get_movie_page": DwMovieRecord,
}
_METHODS = frozenset(_RESULTS) | {
    "get_episodes_paginated", "get_square_show_thumbnails",
    "get_show_id_by_slug", "get_season_id_by_slugs",
}


class MiddlewareClient:
    def __init__(self, access_token=None, request_timeout=30.0, base_url=None,
                 pace_requests=True, pacing_settings=None, token_provider=None):
        self._access_token = access_token
        self._token_provider = token_provider
        self._request_timeout = request_timeout

    def __getattr__(self, name):
        if name not in _METHODS:
            raise AttributeError(name)

        def invoke(*args, **kwargs):
            token = self._access_token or (self._token_provider() if self._token_provider else None)
            # The inherited token store remains the Source connection for the
            # old screens until their account UI is migrated to Source settings.
            if not token and (name == "get_user_info" or
                              name == "get_episode_details" and kwargs.get("require_member_exclusive")):
                from dailywire_authorisation import DeviceAuthClient
                credentials = DeviceAuthClient().get_token()
                token = credentials.access_token if credentials else None

            def encode(value):
                if isinstance(value, (ByNextPage, ByPodcastSeason, ByShowSeason)):
                    return {"type": type(value).__name__, "fields": asdict(value)}
                if is_dataclass(value):
                    return asdict(value)
                return value

            try:
                raw = SourceGateway().call("dailywire", "legacy_call", timeout=120,
                    method=name, args=[encode(arg) for arg in args],
                    kwargs={key: encode(value) for key, value in kwargs.items()},
                    access_token=token)
            except SourceInvocationError as exc:
                status = 401 if exc.code == "authentication_required" else (
                    429 if exc.code == "rate_limited" else None)
                raise MiddlewareAPIError(str(exc), status_code=status) from exc
            if name == "get_episodes_paginated":
                return EpisodesPaginatedResult(
                    [DwEpisodeRecord.model_validate(item) for item in raw["items"]],
                    raw["next_page_url"], raw["has_next"])
            record = _RESULTS.get(name)
            return record.model_validate(raw) if record else raw

        return invoke


class MovieMiddlewareClient(MiddlewareClient):
    pass
