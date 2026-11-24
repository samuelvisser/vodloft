from __future__ import annotations

import calendar
import re
import unicodedata
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime, time
from functools import lru_cache
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from jinja2 import meta, nodes
from jinja2.exceptions import SecurityError, TemplateError, TemplateSyntaxError, UndefinedError

from .custom_metadata import (
    CustomMetadataScope,
    custom_metadata_template_values,
    get_custom_metadata,
    is_allowed_custom_metadata_template_variable,
)
from .custom_index import (
    CustomIndexNotReadyError,
    get_episode_index_assignments,
    indexing_value_definition_keys,
)
from .episode import EpisodeIdentifierInfo
from .filenames import clean_component, clean_value
from .name_length import fit_name, note_filled_value, tracking_output_names
from .output_template_jinja import TypedText, create_output_template_environment
from config import get_settings
from config.settings.submodels import FilenameRestrictionMode

if TYPE_CHECKING:
    from backend.db.models import Episode, Movie, MovieExtra, Video
    from backend.db.models.media_download import MediaDownloadBase
    from backend.utils.music import AlbumPlace

_DOWNLOADS_PREFIX = "/downloads/"
_MAX_RENDERED_PATH_LENGTH = 4096
_SINGLE_BRACE_TEMPLATE_VARIABLE = re.compile(
    r"(?<!\{)\{[A-Za-z_][A-Za-z0-9_]*\}(?!\})"
)

DATE_OUTPUT_TEMPLATE_FIELDS = frozenset({
    "date", "time", "datetime", "year", "month", "day", "hour", "minute", "second", "day_of_year", "day_of_year_reversed",
})
MOVIE_DATE_OUTPUT_TEMPLATE_FIELDS = frozenset({
    f"movie_{field}" for field in DATE_OUTPUT_TEMPLATE_FIELDS
})

COLLECTION_OUTPUT_TEMPLATE_FIELDS = frozenset({
    "collection", "collection_title", "season", "season_name", "season_index", "season_type", "season_number",
    "episode", "episode_title", "title", "source_number", "episode_type", "episode_extra_type",
    "episode_number", "episode_sub_number", "episode_label", "episode_identifier", "episode_published_date",
    "episode_published_time", "episode_published_datetime", "episode_index", "extra_index",
    "collection_author", "collection_site_id", "episode_site_id", "episode_uploader", "duration_seconds",
    "creator_title", "creator_handle", "creator_kind", "section_title", "section_kind",
    "artist", "album", "album_slug", "album_number", "track_number", "track_number_padded",
}) | DATE_OUTPUT_TEMPLATE_FIELDS

# A Video profile keeps single videos and movies with their extras. The movie_* values are empty for a
# single video, and source names the Site the media came from.
VIDEO_OUTPUT_TEMPLATE_FIELDS = frozenset({
    "movie_slug", "movie_title", "movie_extended_title", "movie_author",
    "movie_mature_rating", "movie_duration_seconds",
    "slug", "title", "extended_title",
    "author", "mature_rating", "rating", "duration_seconds", "media_type", "source",
}) | DATE_OUTPUT_TEMPLATE_FIELDS | MOVIE_DATE_OUTPUT_TEMPLATE_FIELDS

COLLECTION_OUTPUT_TEMPLATE_METADATA_SCOPES: frozenset[CustomMetadataScope] = frozenset({"collection"})
VIDEO_OUTPUT_TEMPLATE_METADATA_SCOPES: frozenset[CustomMetadataScope] = frozenset({"movie"})

# These are values likely to be different between Movies and Movie Extra's.
# They are useful for verifying movie and movie extra paths are distinct.
MEDIA_ITEM_UNIQUE_OUTPUT_TEMPLATE_FIELDS = frozenset({
    "slug", "title", "extended_title", "author", "duration_seconds", "media_type",
}) | DATE_OUTPUT_TEMPLATE_FIELDS


class MovieReleaseDateUnavailableError(ValueError):
    """Deprecated: missing movie dates now render as empty values for Jinja conditions."""


def _reject_single_brace_template_variables(output_template: str) -> None:
    """Require all output-template variables to use Jinja expression syntax."""
    if _SINGLE_BRACE_TEMPLATE_VARIABLE.search(output_template):
        raise ValueError(
            "Output template variables must use Jinja syntax such as '{{ collection }}'; "
            "single-brace variables are not supported"
        )


def _parse_output_template(output_template: str) -> nodes.Template:
    """Parse an output template with VODLoft's sandbox and normalized errors."""
    _reject_single_brace_template_variables(output_template)
    environment = create_output_template_environment()
    try:
        return environment.parse(output_template)
    except TemplateSyntaxError as exc:
        location = f" on line {exc.lineno}" if exc.lineno else ""
        raise ValueError(f"Invalid Jinja template{location}: {exc.message}") from exc


# Tasks ask the same few templates the same questions for every episode they pass, and parsing
# a template costs far more than rendering it. A template's text decides each of these answers.
@lru_cache(maxsize=256)
def output_template_fields(output_template: str) -> frozenset[str]:
    """Return all context variables referenced by a Jinja path template."""
    parsed = _parse_output_template(output_template)
    # Jinja reports names assigned only inside conditional branches as
    # undeclared, even when the template sets them in every branch.
    assigned = {
        node.target.name for node in parsed.find_all(nodes.Assign)
        if isinstance(node.target, nodes.Name)
    }
    return frozenset(meta.find_undeclared_variables(parsed) - assigned)


_CUSTOM_INDEX_ARGUMENTS = frozenset({"per", "start", "step"})


def _integer_literal(node: nodes.Expr) -> int | None:
    if isinstance(node, nodes.Neg):
        value = _integer_literal(node.node)
        return None if value is None else -value
    if isinstance(node, nodes.Const) and type(node.value) is int:
        return node.value
    return None


def _check_custom_index_group(node: nodes.Expr) -> None:
    """A Custom Index group must be a plain value of the episode being numbered."""
    from jinja_analysis import PURE_FILTERS
    for candidate in (node, *node.find_all(nodes.Expr)):
        if isinstance(candidate, nodes.Filter):
            if candidate.name == "custom_index":
                raise ValueError("custom_index cannot be grouped by another Custom Index")
            if candidate.name not in PURE_FILTERS:
                raise ValueError(f"custom_index cannot be grouped by the {candidate.name} filter")
        elif isinstance(candidate, nodes.Call):
            raise ValueError("custom_index can only be grouped by values, not by calls")


def output_template_custom_index_calls(output_template: str) -> dict[str, frozenset[str]]:
    """Every literal custom-index key, with how each place that uses it groups it.

    The grouping of a key is the source of its per= expression, or "" without one.
    """
    from jinja_analysis import UnsafeEdit, expression_source
    from .custom_index import is_valid_custom_index_key

    parsed = _parse_output_template(output_template)
    calls: dict[str, set[str]] = {}
    for filter_node in parsed.find_all(nodes.Filter):
        if filter_node.name != "custom_index":
            continue
        if filter_node.args or filter_node.dyn_args or filter_node.dyn_kwargs:
            raise ValueError("custom_index only takes per=, start= and step=")
        source = filter_node.node
        if not isinstance(source, nodes.Const) or not isinstance(source.value, str):
            raise ValueError(
                "custom_index must be applied to a literal key, for example "
                "{{ 'featurettes' | custom_index }}"
            )
        key = source.value
        if not is_valid_custom_index_key(key):
            raise ValueError(f"Invalid custom index key: {key}")
        arguments = {}
        for item in filter_node.kwargs:
            if item.key not in _CUSTOM_INDEX_ARGUMENTS:
                raise ValueError(f"custom_index has no {item.key}= argument; use per=, start= or step=")
            if item.key in arguments:
                raise ValueError(f"custom_index was given {item.key}= twice")
            arguments[item.key] = item.value
        for name in ("start", "step"):
            if name in arguments and _integer_literal(arguments[name]) is None:
                raise ValueError(f"custom_index {name}= must be a whole number, for example {name}=1")
        if "step" in arguments and _integer_literal(arguments["step"]) == 0:
            raise ValueError("custom_index step= cannot be 0")
        grouping = ""
        if "per" in arguments:
            _check_custom_index_group(arguments["per"])
            try:
                grouping = expression_source(arguments["per"])
            except UnsafeEdit:
                grouping = repr(arguments["per"])
        calls.setdefault(key, set()).add(grouping)
    return {key: frozenset(groupings) for key, groupings in calls.items()}


def typed_characters_the_mode_replaces(output_template: str, mode: FilenameRestrictionMode) -> list[str]:
    """Characters typed in the template itself that the filename mode will change.

    Values a template fills in are not counted: they are cleaned as yt-dlp
    cleans them, which is expected. Saving is never refused for these.
    """
    from .filenames import replaced_typed_characters
    parsed = _parse_output_template(output_template)
    typed = "".join(node.data for node in parsed.find_all(nodes.TemplateData))
    return replaced_typed_characters(typed, FilenameRestrictionMode(mode))


@lru_cache(maxsize=256)
def output_template_custom_index_keys(output_template: str) -> frozenset[str]:
    """Return literal custom-index keys referenced by one output template."""
    return frozenset(output_template_custom_index_calls(output_template))


def _statement_may_emit_output(statement: nodes.Stmt) -> bool:
    """Whether a Jinja statement can emit text into the rendered path."""
    if isinstance(statement, (nodes.Assign, nodes.AssignBlock, nodes.Macro)):
        # Assign blocks and macro bodies may contain Output nodes, but their text
        # is captured/defined rather than emitted where the statement appears.
        return False
    if isinstance(statement, nodes.If):
        branches = [*statement.body, *statement.elif_, *statement.else_]
        return any(_statement_may_emit_output(child) for child in branches)
    if isinstance(statement, nodes.For):
        return any(
            _statement_may_emit_output(child)
            for child in [*statement.body, *statement.else_]
        )
    if isinstance(statement, nodes.With):
        return any(_statement_may_emit_output(child) for child in statement.body)
    return True


def _path_boundary_in_branches(
    statements: list[nodes.Stmt], *, start: bool,
) -> bool:
    """Check a literal path boundary on every conditional output branch."""
    ordered = statements if start else list(reversed(statements))
    for statement in ordered:
        if not _statement_may_emit_output(statement):
            continue
        if isinstance(statement, nodes.Output):
            node = statement.nodes[0 if start else -1] if statement.nodes else None
            return isinstance(node, nodes.TemplateData) and (
                node.data.startswith(_DOWNLOADS_PREFIX) if start else node.data.endswith(".ext")
            )
        if isinstance(statement, nodes.If):
            branches = [statement.body, *(branch.body for branch in statement.elif_), statement.else_]
            return bool(statement.else_) and all(
                _path_boundary_in_branches(branch, start=start) for branch in branches
            )
        return False
    return False


def validate_output_template_path_requirements(
    output_template: str,
    *,
    allowed_fields: frozenset[str],
    allowed_metadata_scopes: frozenset[CustomMetadataScope] = frozenset(),
) -> str:
    """Validate save-time path boundaries without interpreting Jinja in the frontend.

    Non-outputting Jinja statements may precede the literal ``/downloads/``
    prefix. Any statement that can render text before that prefix is rejected.
    The raw template still has to end in ``.ext`` so the resulting filename keeps
    VODLoft's extension marker.
    """
    validate_output_template_fields(
        output_template,
        allowed_fields=allowed_fields,
        allowed_metadata_scopes=allowed_metadata_scopes,
    )
    parsed = _parse_output_template(output_template)

    if not _path_boundary_in_branches(parsed.body, start=True):
        raise ValueError("Output template must start with '/downloads/'")
    if not _path_boundary_in_branches(parsed.body, start=False):
        raise ValueError("Output template must end with '.ext'")
    return output_template


def sanitize_path_component(
    value: str,
    *,
    mode: FilenameRestrictionMode = FilenameRestrictionMode.WINDOWS,
    extension: str | None = None,
) -> str:
    """Make one output path component safe according to the configured mode.

    ``extension`` marks the file name, so its extension is kept apart.
    """
    return clean_component(value, FilenameRestrictionMode(mode), extension=extension)


_FILENAME_MODE: ContextVar[FilenameRestrictionMode | None] = ContextVar("vodloft_filename_mode", default=None)


@contextmanager
def rendering_with_filename_mode(mode: FilenameRestrictionMode) -> Iterator[None]:
    """Render values with ``mode`` instead of the configured one, such as for an import's path proof."""
    token = _FILENAME_MODE.set(FilenameRestrictionMode(mode))
    try:
        yield
    finally:
        _FILENAME_MODE.reset(token)


def _sanitize_emitted_output_value(value: object) -> str:
    """Clean each value a template fills in, as yt-dlp does, so it never creates path structure."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # Numbers are not text: a Custom Index of -1 stays -1.
        return str(value)
    mode = _FILENAME_MODE.get() or FilenameRestrictionMode(get_settings().download_settings.filename_restriction_mode)
    # A value marked with as_typed is cleaned with the template's own text, by the name pass.
    text = str(value) if isinstance(value, TypedText) else clean_value(value, mode)
    # Whatever the mode, a value can never add a path level or a line.
    text = text.replace("/", "\u29f8").replace("\x00", "")
    text = "".join(char for char in text if char == "\t" or ord(char) >= 32)
    note_filled_value(text)
    return text


def _sanitize_rendered_path(
    rendered: str,
    *,
    mode: FilenameRestrictionMode,
    extension: str | None = None,
) -> str:
    """Apply filename restrictions after the complete output path is known."""
    relative = rendered[len(_DOWNLOADS_PREFIX):]
    parts = relative.split("/")
    last = len(parts) - 1
    sanitized = [
        fit_name(
            sanitize_path_component(part, mode=mode, extension=extension if index == last else None),
            extension=extension if index == last else None,
        )
        if part
        else ""
        for index, part in enumerate(parts)
    ]
    return _DOWNLOADS_PREFIX + "/".join(sanitized)


def validate_output_template_fields(
    output_template: str,
    *,
    allowed_fields: frozenset[str],
    allowed_metadata_scopes: frozenset[CustomMetadataScope] = frozenset(),
) -> str:
    """Validate Jinja syntax and reject variables unavailable for this media type."""
    output_template_custom_index_keys(output_template)
    unsupported = sorted(
        field
        for field in output_template_fields(output_template)
        if field not in allowed_fields
        and not is_allowed_custom_metadata_template_variable(
            field,
            scopes=allowed_metadata_scopes,
        )
    )
    if unsupported:
        fields = ", ".join("{{ " + field + " }}" for field in unsupported)
        raise ValueError(f"Unsupported output template variable(s): {fields}")
    return output_template


def template_has_media_item_field(output_template: str) -> bool:
    """Whether a Video profile's template references a value that varies by downloaded item, so a movie and its
    extras get paths of their own."""
    return bool(output_template_fields(output_template) & MEDIA_ITEM_UNIQUE_OUTPUT_TEMPLATE_FIELDS)


def movie_template_uses_release_date(output_template: str) -> bool:
    """Whether a movie template references the parent movie's release date."""
    return bool(
        output_template_fields(output_template)
        & (DATE_OUTPUT_TEMPLATE_FIELDS | MOVIE_DATE_OUTPUT_TEMPLATE_FIELDS)
    )


def episode_output_template_values(
    episode: "Episode", *, album_places: "Mapping[int, AlbumPlace] | None" = None,
) -> dict[str, str]:
    """Build the complete Collection-profile context for an episode.

    Whoever builds it for many episodes passes their ``album_places`` (from ``backend.utils.music.album_places``),
    so the track numbers do not take a query per episode.
    """
    episode_identifier = episode.episode_identifier or ""
    ep_info = EpisodeIdentifierInfo.from_identifier(episode_identifier)
    published_at = episode.published_date
    values = {
        "collection": episode.collection.slug,
        "collection_title": episode.collection.title,
        "collection_author": episode.collection.author_name or "",
        "collection_site_id": episode.collection.slug,
        "season": episode.season.slug if episode.season else "",
        "season_name": episode.season.name if episode.season else "",
        "season_index": str(episode.season.index) if episode.season else "",
        "season_type": episode.season.season_type if episode.season else "",
        "season_number": str(episode.season.season_number) if episode.season else "",
        # A Music collection's albums are its seasons, so a Music profile can name them as albums.
        "album_slug": episode.season.slug if episode.season else "",
        "album_number": str(episode.season.season_number) if episode.season else "",
        "episode": episode.slug,
        "episode_index": str(episode.index),
        "extra_index": str(episode.extra_index) if episode.extra_index is not None else "",
        "episode_site_id": episode.source_slug or "",
        "episode_uploader": episode.author_name or "",
        "duration_seconds": str(round(episode.duration or 0)),
        "episode_title": episode.title,
        "title": episode.title,
        "source_number": episode.source_number or "",
        "episode_type": ep_info.type or "",
        "episode_extra_type": ep_info.extra_type or "",
        "episode_number": ep_info.episode_number or "",
        "episode_sub_number": ep_info.sub_episode_number or "",
        "episode_label": ep_info.label,
        "episode_identifier": episode_identifier,
        "episode_published_date": published_at.strftime("%Y-%m-%d") if published_at else "",
        "episode_published_time": published_at.strftime("%H:%M:%S") if published_at else "",
        "episode_published_datetime": published_at.strftime("%Y-%m-%d %H:%M:%S") if published_at else "",
        **_date_substitutions(published_at),
        **_creator_values(episode),
        **_music_values(episode, album_places),
    }
    values.update(custom_metadata_template_values(
        "collection",
        get_custom_metadata(episode.collection),
    ))
    return values


def movie_output_template_values(
    movie: "Movie",
    media_item: "Movie | MovieExtra | None" = None,
) -> dict[str, str]:
    """Build the complete Video-profile context for a movie or one of its extras."""
    item = media_item or movie
    is_movie_extra = getattr(item, "type", None) == "movie_extra"
    media_type = getattr(item, "movie_extra_type", "other") if is_movie_extra else "movie"

    movie_extended_title = movie.extended_title or movie.title
    movie_duration_seconds = str(round(movie.duration or 0))

    if is_movie_extra:
        item_slug = item.slug
        item_title = item.title
        item_extended_title = item.title
        item_author = ""
        item_rating = ""
        item_duration_seconds = str(round(item.duration or 0))
        item_date = getattr(item, "published_date", None)
    else:
        item_slug = movie.slug
        item_title = movie.title
        item_extended_title = movie_extended_title
        item_author = movie.author_name or ""
        item_rating = movie.mature_rating or ""
        item_duration_seconds = movie_duration_seconds
        item_date = getattr(movie, "release_date", None)

    movie_dates = {
        f"movie_{field}": value
        for field, value in _date_substitutions(getattr(movie, "release_date", None)).items()
    }

    values = {
        "movie_slug": movie.slug,
        "movie_title": movie.title,
        "movie_extended_title": movie_extended_title,
        "movie_author": movie.author_name or "",
        "movie_mature_rating": movie.mature_rating or "",
        "movie_duration_seconds": movie_duration_seconds,
        **movie_dates,
        "slug": item_slug,
        "title": item_title,
        "extended_title": item_extended_title,
        "author": item_author,
        "mature_rating": item_rating,
        "rating": item_rating,
        "duration_seconds": item_duration_seconds,
        "media_type": media_type,
        "source": _source_name(getattr(movie, "source_key", "")),
        **_date_substitutions(item_date),
    }
    values.update(custom_metadata_template_values(
        "movie",
        get_custom_metadata(movie),
    ))
    return values


CREATOR_OUTPUT_TEMPLATE_FIELDS = frozenset({"creator_title", "creator_handle", "creator_kind"})
"""The creator values, which are the same for every episode of a collection, so a collection's folder may use them."""


def creator_output_template_values(creator) -> dict[str, str]:
    """The creator a collection is grouped under. Empty without a creator, so a template that uses them stays valid
    for every collection."""
    if creator is None:
        return {field: "" for field in CREATOR_OUTPUT_TEMPLATE_FIELDS}
    account = creator.accounts[0] if creator.accounts else None
    return {
        "creator_title": creator.title,
        "creator_handle": ((account.handle if account is not None else None) or "").lstrip("@"),
        "creator_kind": _creator_kind(creator),
    }


def _creator_values(episode: "Episode") -> dict[str, str]:
    """The episode's creator, and the section of its channel it is from: the playlist that is its season, the list
    the collection is made from, or the feed that brought it, such as Shorts."""
    from backend.services.link_seasons import channel_feeds, episode_tag
    from backend.types.link_season_types import CollectionKind

    collection = episode.collection
    playlist = _episode_list(episode)
    if playlist is not None:
        title, kind = playlist.title, "list"
    elif collection.kind == CollectionKind.LIST.value:
        title, kind = collection.title, "list"
    else:
        tag = episode_tag(episode)
        feed = next((type_ for type_ in channel_feeds(collection) if type_.episode_tag == tag), None)
        title, kind = (feed.title, "feed") if feed is not None else ("", "")
    return {
        **creator_output_template_values(collection.creator),
        "section_title": title,
        "section_kind": kind,
    }


def _episode_list(episode: "Episode"):
    """The list of the episode's season that has it: the season's own list, or, in a season of several lists, the
    first of them that has the episode. In a collection that lays its lists out by year, the first list that has it."""
    if not episode.collection.lists:
        return None
    from backend.services.link_seasons import lists_by_year

    by_year = lists_by_year(episode.collection)
    links = [
        link for link in episode.collection.lists
        if by_year or (episode.season_id is not None and link.season_id == episode.season_id)
    ]
    if len(links) <= 1 and not by_year:
        return links[0] if links else None
    if not links:
        return None
    from sqlalchemy import select
    from sqlalchemy.orm import object_session

    from backend.db.models import CollectionListItem
    from backend.services.season_order import lists_by_season

    s = object_session(episode)
    if s is None:
        return None if by_year else links[0]
    holding = set(s.scalars(select(CollectionListItem.list_id).where(
        CollectionListItem.list_id.in_([link.id for link in links]), CollectionListItem.source_slug == episode.source_slug,
    )))
    if by_year:
        return next((link for link in links if link.id in holding), None)
    ordered = lists_by_season(s, episode.collection).get(episode.season_id, links)
    return next((link for link in ordered if link.id in holding), ordered[0])


def _music_values(episode: "Episode", album_places: "Mapping[int, AlbumPlace] | None") -> dict[str, str]:
    """The episode as a track of an album, for a Music profile."""
    from backend.utils.music import music_track

    track = music_track(episode, album_places)
    number = track.track_number
    return {
        "artist": track.artist,
        "album": track.album,
        "track_number": str(number) if number is not None else "",
        "track_number_padded": f"{number:02d}" if number is not None else "",
    }


def _creator_kind(creator) -> str:
    """What the creator is, such as "YouTube creator", "The Daily Wire host" or, on several Sites, "creator"."""
    from backend.services.creators import creator_kind

    return creator_kind(creator)


def _source_name(source_key: str) -> str:
    from sources import UnknownSourceError, get_source

    try:
        return get_source(source_key).name
    except UnknownSourceError:
        return source_key


def video_output_template_values(video: "Video") -> dict[str, str]:
    """Build the complete Video-profile context for a single video. The movie values stay empty."""
    return {
        **{field: "" for field in VIDEO_OUTPUT_TEMPLATE_FIELDS},
        "slug": video.slug,
        "title": video.title,
        "extended_title": video.title,
        "author": video.author_name or "",
        "duration_seconds": str(round(video.duration or 0)),
        "media_type": "video",
        "source": _source_name(video.source_key),
        **_date_substitutions(video.published_at),
    }


class PreparedOutputTemplate:
    """Validated and compiled output template reusable across many renders."""

    def __init__(
        self,
        output_template: str,
        *,
        allowed_fields: frozenset[str],
        allowed_metadata_scopes: frozenset[CustomMetadataScope] = frozenset(),
    ) -> None:
        self.allowed_fields = allowed_fields
        normalized = validate_output_template_fields(
            output_template,
            allowed_fields=allowed_fields,
            allowed_metadata_scopes=allowed_metadata_scopes,
        )
        referenced_fields = output_template_fields(normalized)
        self.dynamic_fields = frozenset(
            field
            for field in referenced_fields
            if is_allowed_custom_metadata_template_variable(
                field,
                scopes=allowed_metadata_scopes,
            )
        )
        environment = create_output_template_environment()
        environment.finalize = _sanitize_emitted_output_value
        self.template = environment.from_string(normalized)

    def render(self, values: dict[str, object], *, custom_index_resolver=None) -> str:
        context = {
            field: values.get(field, "")
            for field in self.allowed_fields | self.dynamic_fields
        }
        if custom_index_resolver is not None:
            context["__vodloft_custom_index_resolver"] = custom_index_resolver
        try:
            rendered = self.template.render(context)
        except TypeError as exc:
            raise ValueError(str(exc)) from exc
        except (SecurityError, UndefinedError, TemplateError) as exc:
            raise ValueError(f"Could not render Jinja template: {exc}") from exc

        if "\n" in rendered or "\r" in rendered:
            raise ValueError("Rendered output path must be a single line")
        if len(rendered) > _MAX_RENDERED_PATH_LENGTH:
            raise ValueError("Rendered output path is too long")
        if not rendered.startswith(_DOWNLOADS_PREFIX):
            raise ValueError(
                "Rendered output path must start with '/downloads/'. "
                f"Actual output: {rendered!r}"
            )
        if not rendered.endswith(".ext"):
            raise ValueError("Rendered output path must end with '.ext'")
        return rendered


@lru_cache(maxsize=256)
def prepare_output_template(
    output_template: str,
    *,
    allowed_fields: frozenset[str],
    allowed_metadata_scopes: frozenset[CustomMetadataScope] = frozenset(),
) -> PreparedOutputTemplate:
    return PreparedOutputTemplate(
        output_template,
        allowed_fields=allowed_fields,
        allowed_metadata_scopes=allowed_metadata_scopes,
    )


def render_output_template(
    output_template: str,
    values: dict[str, object],
    *,
    allowed_fields: frozenset[str],
    allowed_metadata_scopes: frozenset[CustomMetadataScope] = frozenset(),
    custom_index_resolver=None,
) -> str:
    """Render a path template with raw semantic values in the Jinja context."""
    return prepare_output_template(
        output_template,
        allowed_fields=allowed_fields,
        allowed_metadata_scopes=allowed_metadata_scopes,
    ).render(values, custom_index_resolver=custom_index_resolver)


def resolve_episode_output_path_with_index_values(
    output_template: str,
    *,
    episode: "Episode",
    index_definitions: frozenset[str],
    index_values: dict[str, int],
    filename_mode: FilenameRestrictionMode,
    extension: Optional[str] = None,
    values: dict[str, str] | None = None,
) -> Path:
    """``values`` are the episode's template values, when the caller already has them."""
    def resolver(key: str, _group: object = ()) -> object:
        if key not in index_definitions:
            return ""
        if key not in index_values:
            raise CustomIndexNotReadyError(
                f"Custom index '{key}' is not ready for episode '{episode.slug}'"
            )
        return index_values[key]

    return _render_output_path(
        output_template,
        values if values is not None else episode_output_template_values(episode),
        filename_mode=filename_mode,
        extension=extension,
        allowed_fields=COLLECTION_OUTPUT_TEMPLATE_FIELDS,
        allowed_metadata_scopes=COLLECTION_OUTPUT_TEMPLATE_METADATA_SCOPES,
        custom_index_resolver=resolver,
    )


def resolve_episode_output_path(
    output_template: str,
    *,
    episode: "Episode",
    local_media_profile=None,
    media_download: "MediaDownloadBase | None" = None,
    filename_mode: FilenameRestrictionMode,
    extension: Optional[str] = None,
) -> Path:
    index_keys = output_template_custom_index_keys(output_template)
    if not index_keys:
        return _render_output_path(
            output_template,
            episode_output_template_values(episode),
            filename_mode=filename_mode,
            extension=extension,
            allowed_fields=COLLECTION_OUTPUT_TEMPLATE_FIELDS,
            allowed_metadata_scopes=COLLECTION_OUTPUT_TEMPLATE_METADATA_SCOPES,
        )

    if local_media_profile is None:
        raise CustomIndexNotReadyError(
            "This output template uses custom indexes and requires a Local Media Profile"
        )

    from sqlalchemy.orm import object_session
    from backend.services.custom_indexes import ensure_episode_custom_indexes_ready
    session = object_session(episode)
    if session is None:
        raise CustomIndexNotReadyError("An attached Episode is required for custom index readiness")
    ensure_episode_custom_indexes_ready(session, episode=episode, profile=local_media_profile)

    try:
        return resolve_episode_output_path_with_index_values(
            output_template,
            episode=episode,
            index_definitions=indexing_value_definition_keys(local_media_profile),
            index_values=get_episode_index_assignments(episode, local_media_profile.id),
            filename_mode=filename_mode,
            extension=extension,
        )
    except CustomIndexNotReadyError as exc:
        raise CustomIndexNotReadyError(
            str(exc), repair_collection_id=episode.collection_id,
            repair_profile_id=local_media_profile.id,
        ) from exc


def resolve_movie_output_path(
    output_template: str,
    *,
    movie: "Movie",
    media_item: "Movie | MovieExtra | None" = None,
    filename_mode: FilenameRestrictionMode,
    extension: Optional[str] = None,
) -> Path:
    """Resolve a Video Local Media Profile for a movie or one of its extras."""
    if output_template_custom_index_keys(output_template):
        raise ValueError("custom_index is only available to Collection Local Media Profiles")
    return _render_output_path(
        output_template,
        movie_output_template_values(movie, media_item),
        filename_mode=filename_mode,
        extension=extension,
        allowed_fields=VIDEO_OUTPUT_TEMPLATE_FIELDS,
        allowed_metadata_scopes=VIDEO_OUTPUT_TEMPLATE_METADATA_SCOPES,
    )


def resolve_video_output_path(
    output_template: str,
    *,
    video: "Video",
    filename_mode: FilenameRestrictionMode,
    extension: Optional[str] = None,
) -> Path:
    """Resolve a Video Local Media Profile for a single video."""
    if output_template_custom_index_keys(output_template):
        raise ValueError("custom_index is only available to Collection Local Media Profiles")
    return _render_output_path(
        output_template,
        video_output_template_values(video),
        filename_mode=filename_mode,
        extension=extension,
        allowed_fields=VIDEO_OUTPUT_TEMPLATE_FIELDS,
        allowed_metadata_scopes=VIDEO_OUTPUT_TEMPLATE_METADATA_SCOPES,
    )


def _date_substitutions(value: Optional[date | datetime]) -> dict[str, str]:
    if value is None:
        return {field: "" for field in DATE_OUTPUT_TEMPLATE_FIELDS}
    if isinstance(value, datetime):
        value_datetime = value
    else:
        value_datetime = datetime.combine(value, time.min)
    return {
        "date": value_datetime.strftime("%Y-%m-%d"),
        "time": value_datetime.strftime("%H:%M:%S"),
        "datetime": value_datetime.strftime("%Y-%m-%d %H:%M:%S"),
        "year": value_datetime.strftime("%Y"),
        "month": value_datetime.strftime("%m"),
        "day": value_datetime.strftime("%d"),
        "hour": value_datetime.strftime("%H"),
        "minute": value_datetime.strftime("%M"),
        "second": value_datetime.strftime("%S"),
        "day_of_year": value_datetime.strftime("%j"),
        # Counts down to 001 on the last day of the year, so the newest day of a year sorts first.
        "day_of_year_reversed": f"{_days_in_year(value_datetime.year) + 1 - value_datetime.timetuple().tm_yday:03d}",
    }


def _days_in_year(year: int) -> int:
    return 366 if calendar.isleap(year) else 365


def replace_output_extension(resolved: str, extension: Optional[str]) -> str:
    """Replace VODLoft's .ext marker with a concrete media extension."""
    if extension is not None and resolved.endswith(".ext"):
        return resolved[:-len("ext")] + extension.lstrip(".")
    return resolved


def finalize_output_path(resolved: str, extension: Optional[str], *, mode: FilenameRestrictionMode) -> str:
    """Apply filename restrictions once the concrete filename is known."""
    resolved = replace_output_extension(resolved, extension)
    if extension is None:
        return resolved
    return _sanitize_rendered_path(resolved, mode=mode, extension=extension.lstrip("."))


def _render_output_path(
    output_template: str,
    values: dict[str, object],
    *,
    filename_mode: FilenameRestrictionMode,
    extension: Optional[str],
    **render_options,
) -> Path:
    """Render a profile's template with the profile's filename mode, into a path in the download root."""
    with rendering_with_filename_mode(filename_mode), tracking_output_names():
        rendered = render_output_template(output_template, values, **render_options)
        return _finish_output_path(rendered, extension=extension, mode=filename_mode)


def _finish_output_path(resolved: str, *, extension: Optional[str], mode: FilenameRestrictionMode) -> Path:
    resolved = finalize_output_path(resolved, extension, mode=FilenameRestrictionMode(mode))
    if resolved.startswith(_DOWNLOADS_PREFIX):
        resolved = resolved[len(_DOWNLOADS_PREFIX):]
    resolved = resolved.lstrip("/")

    download_root = Path(get_settings().download_settings.download_root).resolve()
    output_path = (download_root / resolved).resolve()
    if not output_path.is_relative_to(download_root):
        raise ValueError("Rendered output path must stay inside the downloads directory")
    return output_path
