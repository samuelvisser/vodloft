from __future__ import annotations

import logging
import re
from collections.abc import Iterator, Mapping, Sequence
from types import MappingProxyType

from progress_plan import PlanTracker, StageSpec

from ..contract import (
    Access, CollectionArtwork, CollectionDetails, CreatorDetails, FREE_LEVEL, HIGHEST_LEVEL, MembershipLevel, cheapest, Names, SectionType, MAIN_TAG, MIN_NEWEST_EPISODES, SectionKind, SectionRef, EpisodeMedia, EpisodePublishStatus, EpisodeTag, Feature, LinkKind, Playback,
    DownloadOptions, PublishStatusLabel, ResolvedLink, RssEpisodeType, SeasonRef, Site, SiteSetting, SiteSettings, Source, StreamMethod,
    ReleaseDate, UpgradeChecks, UpgradeImprovement, UpgradeOffer, VideoDetails, publish_status_labels_with,
)
from .api.dw_api.client import ByShowSeason, MiddlewareClient
from .api.dw_api.movie import MovieMiddlewareClient
from .api.dw_api.client import ByNextPage, MiddlewareAPIError
from .api.records import DwEpisodeRecord, DwShowRecord
from .api.types.user_info import DwMembershipLevel
from .api.utils.validators.available_for_list import parse_tiers
from .auth import DeviceAuthClient
from .auth.storage import TokenStore
from .links import HOST, _access_token, _first, collection_url, host_url, parse_link, resolve_link
from . import membership
from .membership import LEVEL_ORDER, account_level, check_after_refusal
from .playback import resolve_movie_playback
from .status import is_no_show_today_slug, is_published_final, observe_episode_detail, resolve_episode_status, stream_length

logger = logging.getLogger(__name__)

# Episode numbers .01 to .19 belong to an episode; .20 and up are the show's own extra content.
_SHOW_EXTRA_SEGMENT = 20
# A show's season of extra content, such as "Extras".
_EXTRAS_SEASON = re.compile(r"\bextras?\b", re.IGNORECASE)
_TRAILER_TITLE = re.compile(r"\btrailer\b", re.IGNORECASE)
_PAGE_SIZE = 50
# A collection's membership level that is whatever the signed-in account has.


def _numbers(number_text: str) -> tuple[int | None, int | None]:
    """The episode and extra number of The Daily Wire's own number: 2460 is episode 2460, 2460.10 its tenth extra.
    From .20 up a number is the show's own extra content, which belongs to no episode."""
    whole, _, fraction = number_text.strip().partition(".")
    if not whole.isdigit():
        return None, None
    segment = int(fraction) if fraction.isdigit() else 0
    if segment == 0:
        return int(whole), None
    if segment < _SHOW_EXTRA_SEGMENT:
        return int(whole), segment
    return None, None


def _tag(record: DwEpisodeRecord, *, extras: bool = False) -> str:
    """The episode tag VODLoft gives the record, from its episode number, whether it is a trailer, and whether it is
    in the show's season of extras."""
    number, extra = _numbers(record.episode_number) if not extras else (None, None)
    if record.trailer:
        return "trailer"
    if extra is not None:
        return "ep-extra"
    return MAIN_TAG if number is not None else "aux"


# The Daily Wire's paid membership levels, cheapest first. Their keys are The Daily Wire's own names, and their tiers
# their place among the levels: each level gives everything the ones before it give.
MEMBERSHIP_ACCESSES = tuple(
    Access(level.value, label, f"Only Daily Wire {label} members can watch this.", tier=LEVEL_ORDER.index(level))
    for level, label in (
        (DwMembershipLevel.INSIDER, "Insider"),
        (DwMembershipLevel.INSIDER_PLUS, "Insider Plus"),
        (DwMembershipLevel.ALL_ACCESS, "All Access"),
    )
)


def episode_access(available_for: Sequence[object]) -> str | None:
    """The cheapest membership level an episode is available for, or None when anyone can watch it."""
    if DwMembershipLevel.FREE in available_for:
        return None
    found = cheapest(access for access in MEMBERSHIP_ACCESSES if DwMembershipLevel(access.key) in available_for)
    return found.key if found is not None else None


def _video(
    record: DwEpisodeRecord, season: SeasonRef | None, *, extras: bool = False, author_name: str | None = None,
    status: EpisodePublishStatus = EpisodePublishStatus.PUBLISHED_FINAL,
) -> VideoDetails:
    number, extra = _numbers(record.episode_number) if not extras else (None, None)
    return VideoDetails(
        slug=record.slug,
        url=record.sharing_url,
        title=record.title,
        description=record.description,
        duration=record.duration or None,
        image_url=_first(record.thumbnail_landscape_path, record.background_image_path),
        portrait_image_url=record.thumbnail_portrait_path,
        square_image_url=record.thumbnail_square_path,
        background_url=record.background_image_path,
        # The Daily Wire names no uploader per episode; the show's host uploads them all.
        author_name=author_name,
        published_at=record.published_date,
        season=season,
        episode_number=number,
        extra_number=extra,
        number_text=record.episode_number or None,
        tag=_tag(record, extras=extras),
        access=episode_access(record.available_for),
        publish_status=status,
        scheduled_at=record.scheduled_date,
    )


def video_of(record: DwEpisodeRecord, *, season_name: str | None) -> VideoDetails:
    """An episode record as VODLoft knows it, in the show's season named ``season_name``."""
    return _video(record, None, extras=bool(_EXTRAS_SEASON.search(season_name or "")))


def _season_refs(show: DwShowRecord) -> dict[str, tuple[SeasonRef, bool]]:
    """Each season of the show by its slug, numbered as VODLoft numbers them: its seasons from 1, oldest first, and
    its season of extras 0; with whether it is that season."""
    refs: dict[str, tuple[SeasonRef, bool]] = {}
    number = 0
    for season in show.seasons:
        extras = bool(_EXTRAS_SEASON.search(season.name or ""))
        if not extras:
            number += 1
        refs[season.slug] = (SeasonRef(slug=season.slug, number=0 if extras else number, title=season.name), extras)
    return refs


def _show_slug(url: str) -> str:
    parsed = parse_link(url)
    if parsed is None or parsed[0] is not LinkKind.COLLECTION:
        raise ValueError("This is not a link to a show on The Daily Wire")
    return parsed[1]


def _ref(refs: dict[str, tuple[SeasonRef, bool]], slug: str) -> tuple[SeasonRef | None, bool]:
    return refs.get(slug, (None, False))


def _trailer_checked(client: MiddlewareClient, record: DwEpisodeRecord, *, members: bool) -> DwEpisodeRecord:
    """The record, or its details where its title calls it a trailer and only the details can say whether it is: a
    page of episodes leaves the flag out, and the flag is wrong for some trailers called Official Trailer."""
    if record.is_trailer is True or record.trailer or not _TRAILER_TITLE.search(record.title or ""):
        return record
    try:
        return client.get_episode_details(record.slug, require_member_exclusive=members)
    except MiddlewareAPIError as exc:
        if exc.status_code != 404:
            raise
        return record


def _resolved(
    client: MiddlewareClient, record: DwEpisodeRecord, season: SeasonRef | None, *, extras: bool, members: bool,
    look_up: bool, author_name: str | None,
) -> VideoDetails | None:
    """A new episode, with where it is in its life from its details. In a whole listing one out long enough ago to be
    final is not looked up (``look_up`` False). None when The Daily Wire has nothing usable for it."""
    if not look_up and is_published_final(record):
        record = _trailer_checked(client, record, members=members)
        return _video(record, season, extras=extras, author_name=author_name)
    try:
        detail = client.get_episode_details(record.slug, require_member_exclusive=members)
    except MiddlewareAPIError as exc:
        if exc.status_code != 404:
            raise
        logger.info("The Daily Wire has no details of new episode %s", record.slug)
        return None
    status = resolve_episode_status(
        detail, publication_timing_reference=detail.published_date, snapshot=observe_episode_detail(detail),
    ).status
    if status is None:
        return None
    return _video(detail, season, extras=extras, author_name=author_name, status=status)


def _membership_plan(membership: str | None) -> str:
    """The membership level a show is listed with. The highest level the account has is listed as free, as VODLoft
    has always done."""
    plan = membership or DwMembershipLevel.FREE.value
    return DwMembershipLevel.FREE.value if plan == HIGHEST_LEVEL else plan


_VIDEO_HEIGHTS = (480, 720, 1080)


class DailyWireSource(Source):
    id = "dailywire"
    name = "The Daily Wire"
    domains = ("dailywire.com",)
    sites = (Site(
        "dailywire", "The Daily Wire", domains,
        # A custom icon in VODLoft's Font Awesome Kit: The Daily Wire's DW letters.
        icon="fak:dailywire", initials="DW",
        # Its own sign-in is how VODLoft signs in; no Source signs in on it with cookies.
        takes_cookies=False,
        stream_methods=frozenset({StreamMethod.FILE, StreamMethod.HLS, StreamMethod.LIVE}),
        stream_video_heights=_VIDEO_HEIGHTS,
        # Fixed versions: an HLS stream of 480p, 720p and 1080p, and audio, with its own subtitles.
        downloads=DownloadOptions(video_heights=_VIDEO_HEIGHTS, hls_heights=_VIDEO_HEIGHTS, subtitles=True),
        # The Daily Wire sometimes edits an episode after it is out, such as cutting a long live stream down.
        upgrade_checks=UpgradeChecks((UpgradeImprovement.LENGTH,)),
        settings=SiteSettings(
            # It publishes live episodes with a countdown in the recording at first, so a Download Profile can
            # download them with the countdown and again once the final version is out.
            shows=frozenset({SiteSetting.DOWNLOAD_WITH_COUNTDOWN}),
            # It makes no subtitles of its own.
            hides=frozenset({SiteSetting.AUTO_SUBTITLES}),
            presets=MappingProxyType({
                SiteSetting.METADATA_REFRESH: "15m,30m,1h,3h,6h,24h,3d",
                SiteSetting.DOWNLOAD_WITH_COUNTDOWN: False,
                SiteSetting.UPGRADE_CHECK: True,
                SiteSetting.UPGRADE_AFTER_DAYS: 3,
                SiteSetting.UPGRADE_IMPROVEMENTS: [UpgradeImprovement.LENGTH.value],
            }),
        ),
        accesses=MEMBERSHIP_ACCESSES,
        # A host has no feed to fold into one show: each of their shows keeps its own seasons.
        creators=True,
        movies=True,
        show_numbers=True,
        renames_pending=True,
        pitch="Shows and movies, with your membership",
        creator_names=HOST,
        channel_collection_names=Names("show", "shows"),
        section_types=(
            SectionType("show", SectionKind.SHOW, Names("show", "shows")),
            SectionType("movie", SectionKind.ITEM, Names("movie", "movies")),
        ),
        episode_tags=(
            EpisodeTag(MAIN_TAG, "Episode", "A normal episode of the show", Names("episode", "episodes"), main=True),
            EpisodeTag(
                "ep-extra", "Ep. Extra", "Extra content for a specific episode", Names("episode extra", "episode extras"), selected_by_default=False,
                rss_episode_type=RssEpisodeType.BONUS,
            ),
            EpisodeTag(
                "trailer", "Trailer", "A trailer for the show or its extra content", Names("trailer", "trailers"), selected_by_default=False,
                rss_episode_type=RssEpisodeType.TRAILER,
            ),
            EpisodeTag("aux", "Auxiliary", "Extra content for the show", Names("auxiliary episode", "auxiliary episodes"), rss_episode_type=RssEpisodeType.BONUS),
        ),
    ),)
    kind_names = MappingProxyType({LinkKind.COLLECTION: Names("show", "shows"), LinkKind.CREATOR: HOST})
    features = frozenset({
        Feature.COLLECTIONS,
        Feature.OWN_SEASONS,
        Feature.MOVIES,
        Feature.MOVIE_EXTRAS,
        Feature.BROWSE,
        Feature.LOGIN,
        Feature.LIVE_EPISODES,
        Feature.MEMBERSHIP_LEVELS,
        Feature.EPISODE_LOOKUPS,
        Feature.EPISODE_LISTS,
        Feature.COLLECTION_DETAILS,
        Feature.OWN_STUDIO,
        Feature.CREATORS,
    })
    release_date = ReleaseDate.END
    publish_status_labels = publish_status_labels_with(
        PublishStatusLabel(EpisodePublishStatus.SCHEDULED, "Scheduled", "The Daily Wire has scheduled the episode."),
        PublishStatusLabel(
            EpisodePublishStatus.DELAYED, "Officially delayed", "The Daily Wire has delayed the start of the episode.",
        ),
        PublishStatusLabel(
            EpisodePublishStatus.SOURCE_PROCESSING, "Processing at The Daily Wire",
            "The episode has ended, but The Daily Wire is still preparing the recording.",
        ),
        PublishStatusLabel(
            EpisodePublishStatus.PUBLISHED_PRELIMINARY, "Published (still contains countdown)",
            "Published, but the recording still opens with the countdown. VODLoft downloads it again once The Daily Wire removes it.",
        ),
    )

    def collection_ref(self, url: str) -> str | None:
        parsed = parse_link(url)
        return parsed[1] if parsed is not None and parsed[0] is LinkKind.COLLECTION else None

    def resolve(self, url: str, plan: PlanTracker | None = None) -> ResolvedLink | None:
        return resolve_link(url, plan)

    membership_levels = (
        MembershipLevel(FREE_LEVEL, "Free", "Access to free content only"),
        MembershipLevel(DwMembershipLevel.INSIDER.value, "Insider", "Access to free content and insider content"),
        MembershipLevel(
            DwMembershipLevel.INSIDER_PLUS.value, "Insider Plus", "Access to insider content and insider plus content",
        ),
        MembershipLevel(DwMembershipLevel.ALL_ACCESS.value, "All Access", "Access to all content"),
    )

    def collection_details(self, url: str) -> CollectionDetails:
        """The show's page: its seasons, oldest first, and its host. It lists with the membership level of the
        signed-in account, as far as VODLoft knows it."""
        show = MiddlewareClient(access_token=_access_token(), request_priority="interactive").get_show_page(
            slug=_show_slug(url),
        )
        level = account_level()
        return CollectionDetails(
            slug=show.slug, url=collection_url(show.slug), title=show.title, description=show.description,
            image_url=show.thumbnail_landscape_path, author_name=show.author_name,
            author_url=host_url(show.author_slug) if show.author_slug else None, author_image_url=show.author_headshot_path,
            seasons=tuple(ref for ref, _extras in _season_refs(show).values()),
            membership_level=level.value if level in LEVEL_ORDER and level is not DwMembershipLevel.READER else FREE_LEVEL,
            probable_type=show.probable_collection_type.value,
        )

    def newest_episodes(self, url: str) -> list[VideoDetails]:
        """The episodes on the show's page, which lists its newest season's latest ones.
        When that page has fewer than a handful, the newest seasons' first pages fill them up."""
        client = MiddlewareClient(access_token=_access_token(), request_priority="interactive")
        show = client.get_show_page(slug=_show_slug(url))
        refs = _season_refs(show)
        found = [(record, show.latest_season.slug) for record in dict.fromkeys(show.latest_episodes)]
        for season in reversed(show.seasons):
            if len(found) >= MIN_NEWEST_EPISODES:
                break
            page = client.get_episodes_paginated(show.slug, ByShowSeason(season_dw_id=season.dw_id, page_size=_PAGE_SIZE))
            known = {record.slug for record, _ in found}
            found += [(record, season.slug) for record in dict.fromkeys(page.items) if record.slug not in known]
        found.sort(key=lambda item: item[0].published_date, reverse=True)
        videos = []
        for record, season_slug in found:
            season, extras = _ref(refs, season_slug)
            videos.append(_video(record, season, extras=extras, author_name=show.author_name))
        return videos

    def list_episodes(
        self, url: str, *, known: frozenset[str], feeds: frozenset[str] | None = None,
        membership: str | None = None,
    ) -> Iterator[VideoDetails]:
        """The show's episodes, season by season. Without ``known`` episodes every season is listed whole; otherwise
        each season newest first, up to the first episode VODLoft has that is out for good, so only what is new is
        read. Each new episode is looked up on its own for where it is in its life, except, in a whole listing, one
        out long enough ago to be final. One with nothing usable, such as a No Show Today placeholder, is left out."""
        slug = _show_slug(url)
        plan = _membership_plan(membership)
        token = _access_token()
        if plan != DwMembershipLevel.FREE.value and token is None:
            logger.warning("Not signed in to The Daily Wire, so %s can't be listed for its members", slug)
            return
        client = MiddlewareClient(access_token=token)
        members = plan != DwMembershipLevel.FREE.value
        show = client.get_show_page(slug, membership_plan=plan)
        refs = _season_refs(show)
        whole = not known
        for season in reversed(show.seasons):
            records = self._season_records(client, slug, season.dw_id, plan, known=known, whole=whole)
            ref, extras = _ref(refs, season.slug)
            for record in records:
                if record.slug in known or is_no_show_today_slug(record.slug):
                    continue
                video = _resolved(client, record, ref, extras=extras, members=members, look_up=not whole, author_name=show.author_name)
                if video is not None:
                    yield video
            if not whole and not extras and any(record.slug in known and is_published_final(record) for record in records):
                # Every season before this one is older than an episode VODLoft has had for good.
                return

    @staticmethod
    def _season_records(
        client: MiddlewareClient, slug: str, season_id: str, plan: str, *, known: frozenset[str], whole: bool,
    ) -> list[DwEpisodeRecord]:
        """A season's episodes: all of them, or the newest ones up to the first one VODLoft has that is out for good."""
        page = client.get_episodes_paginated(slug, ByShowSeason(
            season_dw_id=season_id, membership_plan=plan, page_size=_PAGE_SIZE,
            order_by="CreatedAt_ASC" if whole else "CreatedAt_DESC",
        ))
        records = list(page.items or ())
        while page.has_next and page.next_page_url:
            if not whole and any(record.slug in known and is_published_final(record) for record in records):
                break
            page = client.get_episodes_paginated(slug, ByNextPage(next_page_url=page.next_page_url))
            records += page.items or ()
        # A next page can repeat an episode of the one before.
        return list({record.slug: record for record in records}.values())

    def numbers_of(self, number_text: str) -> tuple[int | None, int | None]:
        return _numbers(number_text)

    def collection_artwork(self, url: str, *, first: bool = False) -> CollectionArtwork | None:
        """The show page's pictures. Its square one, when the page has none, is on the Watch page, which a first
        index looks at too."""
        slug = _show_slug(url)
        client = MiddlewareClient(access_token=_access_token())
        show = client.get_show_page(slug)
        square = show.thumbnail_square_path
        if square is None and first:
            square = client.get_square_show_thumbnails().get(slug)
        return CollectionArtwork(
            portrait=show.thumbnail_portrait_path, landscape=show.thumbnail_landscape_path, square=square,
            background=show.background_image_path, logo=show.logo_image_path,
        )

    def creator_of(self, url: str) -> str | None:
        """The host of a show."""
        slug = self.collection_ref(url)
        if slug is None:
            return None
        catalog = MiddlewareClient(access_token=_access_token(), request_priority="interactive").get_catalog()
        return next((show.author_slug for show in catalog.collections if show.slug == slug and show.author_slug), None)

    def creator_details(self, ref: str, plan: PlanTracker | None = None) -> CreatorDetails:
        """A host, by the slug The Daily Wire gives them or by the link to their page, such as
        https://www.dailywire.com/hosts/ben-shapiro: their shows and movies from the Browse page."""
        if ref.startswith("http"):
            parsed = parse_link(ref)
            if parsed is None or parsed[0] is not LinkKind.CREATOR:
                raise ValueError("This is not a link to a host on The Daily Wire")
            ref = parsed[1]
        plan = plan or PlanTracker()
        plan.add(StageSpec(id="catalog", code="read_catalog", label="Reading The Daily Wire's shows and movies"))
        with plan.running("catalog"):
            catalog = MiddlewareClient(access_token=_access_token(), request_priority="interactive").get_catalog()
        shows = [show for show in catalog.collections if show.author_slug == ref]
        movies = [movie for movie in catalog.movies if movie.author_slug == ref]
        if not shows and not movies:
            raise ValueError("The Daily Wire has no host by that name")
        first = shows[0] if shows else None
        sections = tuple(
            SectionRef(
                ref=show.slug, url=collection_url(show.slug), title=show.title, type=self.sites[0].section_type("show"),
                image_url=_first(show.thumbnail_landscape_path, show.background_image_path),
                description=show.description,
            )
            for show in shows
        ) + tuple(
            SectionRef(
                ref=movie.slug, url=f"https://www.dailywire.com/videos/{movie.slug}", title=movie.title,
                type=self.sites[0].section_type("movie"),
                image_url=_first(movie.thumbnail_landscape_path, movie.thumbnail_portrait_path),
                description=movie.description,
            )
            for movie in movies
        )
        name = (first.author_name if first else None) or (movies[0].author_name if movies else None) or ref
        return CreatorDetails(
            ref=ref, url=None, title=name, avatar_url=first.author_headshot_path if first else None,
            banner_url=first.background_image_path if first else None, sections=sections,
            # The Daily Wire's creators are hosts, never music artists.
            music_known=True,
        )

    def episode_media(self, *, slug: str, members_only: bool, interactive: bool = False) -> EpisodeMedia:
        client = MiddlewareClient(request_priority="interactive") if interactive else MiddlewareClient()
        detail = client.get_episode_details(slug, require_member_exclusive=members_only)
        return EpisodeMedia(video_url=detail.video_url, audio_url=detail.audio_url)

    def has_access(self, key: str) -> bool | None:
        # A lower level does not say False: VODLoft has always let a download find that out.
        level = account_level()
        needed = next((access for access in MEMBERSHIP_ACCESSES if access.key == key), None)
        if level not in LEVEL_ORDER or needed is None:
            return None
        return True if Access(level.value, "", "", tier=LEVEL_ORDER.index(level)).gives(needed) else None

    def learn_access(self) -> None:
        membership.look_up_level()

    def download_refused(self, key: str) -> None:
        if any(access.key == key for access in MEMBERSHIP_ACCESSES):
            check_after_refusal()

    def current_access(self, *, slug: str, url: str) -> str | None:
        payload = MiddlewareClient().get_episode_payload(slug)
        return episode_access(parse_tiers(payload.get("availableFor")))

    def upgrade_offer(self, url: str, *, sponsorblock_categories: Sequence[str] = ()) -> UpgradeOffer:
        """The length of the episode's stream as The Daily Wire serves it now. The listed runtime is
        only a hint, so the playlist itself is measured."""
        parsed = parse_link(url)
        if parsed is None or parsed[0] is not LinkKind.EPISODE:
            raise ValueError("This is not a link to an episode on The Daily Wire")
        detail = MiddlewareClient().get_episode_details(
            parsed[1], require_member_exclusive=DeviceAuthClient().get_token() is not None,
        )
        return UpgradeOffer(duration=stream_length(detail.video_url) if detail.video_url else None)

    def movie_playback(
        self, *, movie_slug: str, title: str, duration: float | None,
        extra_slug: str | None = None, is_extra: bool = False, is_official_trailer: bool = False,
    ) -> Playback:
        tokens = DeviceAuthClient().get_token()
        client = MovieMiddlewareClient(access_token=tokens.access_token if tokens else None)
        selection = resolve_movie_playback(
            client, movie_slug=movie_slug, title=title, duration=duration,
            is_extra=is_extra, extra_slug=extra_slug, is_official_trailer=is_official_trailer,
        )
        return Playback(url=selection.url, metadata=selection.metadata)

    def import_sign_in(self, records: Mapping[str, str]) -> None:
        store = TokenStore()
        for store_key, record in records.items():
            store.store_record(store_key, str(record))
        membership.look_up_level()
