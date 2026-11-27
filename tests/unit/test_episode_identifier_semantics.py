from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace


def _record(
    episode_number: str,
    *,
    slug: str | None = None,
    title: str = "Episode",
    is_trailer: bool | None = None,
):
    from sources.dailywire.api.records import DwEpisodeRecord

    return DwEpisodeRecord(
        dw_id=f"remote-{slug or episode_number}",
        slug=slug or f"episode-{episode_number.replace('.', '-')}",
        title=title,
        description=None,
        duration=3600,
        episode_number=episode_number,
        display_episode_number="",
        background_image_path=None,
        sharing_url="https://example.test/episode",
        publish_status="PUBLISHED",
        is_downloadable=True,
        is_trailer=is_trailer,
        available_for=[],
        thumbnail_landscape_path=None,
        thumbnail_portrait_path=None,
        thumbnail_square_path=None,
        published_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        scheduled_date=None,
    )


def _season(*, season_number: int = 1, season_type: str = "normal"):
    return SimpleNamespace(
        id=season_number + 100,
        index=season_number,
        season_number=season_number,
        season_type=season_type,
        slug=f"season-{season_number}",
        name=f"Season {season_number}",
    )


def test_episode_identifier_info_parses_all_canonical_semantics():
    from backend.utils.episode import EpisodeIdentifierInfo

    main = EpisodeIdentifierInfo.from_identifier("ep.S02E27")
    assert main.type == "ep"
    assert main.season_number == 2
    assert main.episode_number == "27"
    assert main.sub_episode_number is None
    assert main.label == "S02E27"

    extra = EpisodeIdentifierInfo.from_identifier("ep-extra.trailer.S02E27.5")
    assert extra.type == "ep-extra"
    assert extra.extra_type == "trailer"
    assert extra.season_number == 2
    assert extra.episode_number == "27"
    assert extra.sub_episode_number == "5"
    assert extra.label == "S02E27.5"

    auxiliary = EpisodeIdentifierInfo.from_identifier("aux.12")
    assert auxiliary.type == "aux"
    assert auxiliary.episode_number == "12"


def _identify(identification, *records, season=None, taken=None, extras=False):
    """The identifiers indexing gives The Daily Wire's records, one after the other, in one season."""
    from backend.services.episode_numbering import CountedNumbers, Numbering, identify
    from sources.dailywire.source import DailyWireSource, video_of

    season = season or _season()
    taken = set() if taken is None else taken
    numbers = CountedNumbers(taken)
    return [
        identify(
            identification, DailyWireSource.sites[0], season,
            Numbering.of_video(video_of(record, season_name="Extras" if extras else season.name), record.published_date),
            taken, numbers,
        )
        for record in records
    ]


def test_extra_before_main_does_not_reserve_main_number():
    from backend.types.collection_types import EpisodeIdentifier

    assert _identify(
        EpisodeIdentifier.NUMBERED, _record("1645.01", slug="extra-first"), _record("1645.00", slug="main-later"),
    ) == ["ep-extra.other.1645.1", "ep.1645"]


def test_extra_can_arrive_after_a_newer_main():
    from backend.types.collection_types import EpisodeIdentifier

    assert _identify(EpisodeIdentifier.NUMBERED, _record("1843.01"), taken={"ep.1843", "ep.1844"}) == [
        "ep-extra.other.1843.1",
    ]


def test_dailywire_segments_20_and_above_are_show_auxiliary_content():
    from backend.types.collection_types import EpisodeIdentifier

    assert _identify(
        EpisodeIdentifier.NUMBERED,
        _record("2000.19", slug="attached-extra"), _record("2000.20", slug="first-aux"), _record("2000.30", slug="second-aux"),
    ) == ["ep-extra.other.2000.19", "aux.1", "aux.2"]


def test_dailywire_segments_20_and_above_are_auxiliary_for_seasonal_shows():
    from backend.types.collection_types import EpisodeIdentifier

    assert _identify(EpisodeIdentifier.SEASONAL, _record("42.20"), season=_season(season_number=3)) == ["aux.1"]


def test_extras_season_numbers_do_not_create_episode_relationships():
    from backend.types.collection_types import EpisodeIdentifier

    assert _identify(
        EpisodeIdentifier.SEASONAL,
        _record("27.00", slug="standalone-main-shaped"), _record("27.10", slug="standalone-extra-shaped"),
        season=_season(season_number=0, season_type="extra"), extras=True,
    ) == ["aux.1", "aux.2"]


def test_attached_trailer_remains_episode_extra_with_trailer_subtype():
    from backend.types.collection_types import EpisodeIdentifier

    assert _identify(EpisodeIdentifier.NUMBERED, _record("2083.05", is_trailer=True)) == ["ep-extra.trailer.2083.5"]


def test_standalone_trailer_counts_after_the_collections_highest_trailer():
    from backend.types.collection_types import EpisodeIdentifier

    assert _identify(EpisodeIdentifier.NUMBERED, _record("2083.00", is_trailer=True)) == ["trailer.1"]
    assert _identify(EpisodeIdentifier.NUMBERED, _record("2083.00", is_trailer=True), taken={"trailer.4"}) == ["trailer.5"]


def test_official_trailer_title_overrides_false_dailywire_flag():
    from backend.types.collection_types import EpisodeIdentifier

    record = _record("2083.00", title="Official Trailer", is_trailer=False)
    assert _identify(EpisodeIdentifier.NUMBERED, record) == ["trailer.1"]


def test_a_trailer_and_another_extra_of_one_number_share_its_place():
    from backend.types.collection_types import EpisodeIdentifier

    assert _identify(
        EpisodeIdentifier.NUMBERED,
        _record("2083.05", slug="first", is_trailer=False), _record("2083.05", slug="duplicate", is_trailer=True),
    ) == ["ep-extra.other.2083.5", "aux.1"]


def test_same_episode_number_is_distinct_across_seasons():
    from backend.types.collection_types import EpisodeIdentifier

    taken: set[str] = set()
    first = _identify(EpisodeIdentifier.SEASONAL, _record("27.00"), season=_season(season_number=1), taken=taken)
    second = _identify(EpisodeIdentifier.SEASONAL, _record("27.00"), season=_season(season_number=2), taken=taken)
    assert (first, second) == (["ep.S01E27"], ["ep.S02E27"])


def test_by_date_an_extra_is_dated_and_a_trailer_of_an_episode_is_a_trailer():
    from backend.types.collection_types import EpisodeIdentifier

    assert _identify(
        EpisodeIdentifier.DATE_BASED, _record("10.01", slug="extra"), _record("10.02", slug="trailer", is_trailer=True),
    ) == ["ep.2026-01-01T00:00:00.000000", "trailer.1"]


def test_by_date_a_second_episode_of_the_same_moment_is_auxiliary():
    from backend.types.collection_types import EpisodeIdentifier

    assert _identify(EpisodeIdentifier.DATE_BASED, _record("10.00", slug="a"), _record("11.00", slug="b")) == [
        "ep.2026-01-01T00:00:00.000000", "aux.1",
    ]


def test_counted_sources_number_their_episodes_themselves():
    """A Site without numbers of its own across a show, such as YouTube: a Numbered collection counts its episodes."""
    from backend.services.episode_numbering import CountedNumbers, Numbering, identify
    from backend.types.collection_types import EpisodeIdentifier
    from sources import Site

    site = Site("example", "Example", ("example.test",))
    taken = {"ep.3"}
    numbering = Numbering(published=datetime(2026, 1, 1, tzinfo=timezone.utc), number=40)
    assert identify(EpisodeIdentifier.NUMBERED, site, _season(), numbering, taken, CountedNumbers(taken)) == "ep.4"
    assert identify(EpisodeIdentifier.SEASONAL, site, _season(), numbering, taken, CountedNumbers(taken)) == "ep.S01E40"


def test_stored_episodes_are_numbered_from_their_identifier_and_the_sources_number():
    from backend.services.episode_numbering import Numbering
    from sources.dailywire.source import DailyWireSource

    source, published = DailyWireSource(), datetime(2026, 1, 1, tzinfo=timezone.utc)
    # An extra a date-based collection dated like an episode is an extra again.
    dated_extra = Numbering.of_stored(source, "ep.2026-01-01T00:00:00.000000", "2460.10", published)
    assert (dated_extra.tag, dated_extra.number, dated_extra.extra) == ("ep-extra", 2460, 10)
    trailer = Numbering.of_stored(source, "ep-extra.trailer.2460.3", "2460.03", published)
    assert (trailer.tag, trailer.number, trailer.extra) == ("trailer", 2460, 3)
    main = Numbering.of_stored(source, "ep.2460", "2460", published)
    assert (main.main, main.number) == (True, 2460)
    assert Numbering.of_stored(source, "aux.2", "2460.20", published).tag == "aux"


def test_background_reindex_verifies_ambiguous_trailer_title_with_detail():
    from backend.db.background_migrations.versions.f6a1c3d8b427_episode_indexing_semantics import (
        _resolve_possible_trailer,
    )

    record = _record(
        "2083.05",
        slug="episode-2083-trailer-discussion",
        title="Episode 2083 Trailer Discussion",
        is_trailer=False,
    )
    detail = record.model_copy(update={"is_trailer": False})
    detail_calls: list[str] = []

    class FakeClient:
        def get_episode_details(self, slug, *, require_member_exclusive):
            detail_calls.append(slug)
            return detail

    resolved = _resolve_possible_trailer(
        FakeClient(),
        record,
        require_member_exclusive=False,
    )

    assert detail_calls == [record.slug]
    assert resolved.is_trailer is False


def test_background_reindex_accepts_true_paginated_trailer_flag_without_detail():
    from backend.db.background_migrations.versions.f6a1c3d8b427_episode_indexing_semantics import (
        _resolve_possible_trailer,
    )

    record = _record(
        "2083.05",
        slug="episode-2083-preview",
        title="Episode 2083 Preview",
        is_trailer=True,
    )

    class FakeClient:
        def get_episode_details(self, slug, *, require_member_exclusive):
            raise AssertionError("Positive paginated isTrailer needs no detail lookup")

    resolved = _resolve_possible_trailer(
        FakeClient(),
        record,
        require_member_exclusive=False,
    )

    assert resolved is record


def test_background_reindex_skips_detail_lookup_for_official_trailer_title():
    from backend.db.background_migrations.versions.f6a1c3d8b427_episode_indexing_semantics import (
        _resolve_possible_trailer,
    )

    record = _record(
        "0.10",
        slug="real-history-with-matt-walsh",
        title="Real History with Matt Walsh | Official Trailer",
        is_trailer=None,
    )

    class FakeClient:
        def get_episode_details(self, slug, *, require_member_exclusive):
            raise AssertionError("Explicit Official Trailer titles need no detail lookup")

    resolved = _resolve_possible_trailer(
        FakeClient(),
        record,
        require_member_exclusive=False,
    )

    assert resolved is record


def test_background_reindex_uses_the_same_canonical_identifier_rules():
    from backend.db.background_migrations.versions.f6a1c3d8b427_episode_indexing_semantics import (
        _direct_identifier,
        _generated_type,
    )

    other = _record("1645.01", slug="migration-extra")
    assert _direct_identifier(
        "numbered",
        season_type="normal",
        season_number=1,
        record=other,
    ) == ("ep-extra.other.1645.1", "1645.1")
    assert _generated_type(
        "numbered",
        season_type="normal",
        record=other,
    ) is None

    attached_trailer = _record(
        "2083.05",
        slug="migration-trailer",
        title="Episode 2083 | Official Trailer",
        is_trailer=False,
    )
    assert _direct_identifier(
        "seasonal",
        season_type="normal",
        season_number=2,
        record=attached_trailer,
    ) == ("ep-extra.trailer.S02E2083.5", "S02E2083.5")

    high_segment = _record("1645.20", slug="high-segment")
    assert _direct_identifier(
        "numbered",
        season_type="normal",
        season_number=1,
        record=high_segment,
    ) == (None, None)
    assert _generated_type(
        "numbered",
        season_type="normal",
        record=high_segment,
    ) == "aux"

    extras_item = _record("27.10", slug="extras-item")
    assert _direct_identifier(
        "seasonal",
        season_type="extra",
        season_number=0,
        record=extras_item,
    ) == (None, None)
    assert _generated_type(
        "seasonal",
        season_type="extra",
        record=extras_item,
    ) == "aux"

    extras_trailer = _record(
        "0.10",
        slug="real-history-with-matt-walsh",
        title="Real History with Matt Walsh | Official Trailer",
        is_trailer=False,
    )
    assert _generated_type(
        "seasonal",
        season_type="extra",
        record=extras_trailer,
    ) == "trailer"


def test_background_reindex_only_updates_raw_number_when_remote_record_exists():
    from backend.db.background_migrations.versions.f6a1c3d8b427_episode_indexing_semantics import (
        LocalEpisode,
        LocalSeason,
        LocalCollection,
        _plan_collection,
    )

    season = LocalSeason(
        id=11,
        slug="season-1",
        season_type="normal",
        season_number=1,
    )
    matched = LocalEpisode(
        id=101,
        season_id=11,
        index=1,
        slug="matched",
        identifier="ep.1",
        previous_identifier=None,
    )
    missing = LocalEpisode(
        id=102,
        season_id=11,
        index=2,
        slug="missing",
        identifier="ep.2",
        previous_identifier=None,
    )
    collection = LocalCollection(
        id=1,
        slug="test-collection",
        sharing_url="https://www.dailywire.com/show/test-show",
        membership_level="FREE",
        identifier_mode="numbered",
        seasons=(season,),
        episodes=(matched, missing),
        latest_aux_num=0,
        latest_trailer_num=0,
    )
    remote = _record("", slug="matched")

    plan = _plan_collection(collection, {11: {"matched": remote}})
    by_id = {episode.episode_id: episode for episode in plan.episodes}

    assert by_id[101].update_source_number is True
    assert by_id[101].source_number is None
    assert by_id[102].update_source_number is False
    assert by_id[102].identifier == "ep.2"



def test_background_reindex_downgrade_restores_previous_identifier_grammar():
    from importlib import import_module

    migration = import_module(
        "importer.wireloft.migrations.6d4a8c1f2b90_wireloft_1_2"
    )
    _identifier_for_previous_release = migration._identifier_for_previous_release

    assert _identifier_for_previous_release(
        "numbered",
        season_index=4,
        identifier="ep-extra.other.1843.10",
    ) == "ep-extra.1843.10"
    assert _identifier_for_previous_release(
        "numbered",
        season_index=4,
        identifier="ep-extra.trailer.1843.5",
    ) == "ep-extra.1843.5"
    assert _identifier_for_previous_release(
        "seasonal",
        season_index=9,
        identifier="ep.S06E570",
    ) == "ep.S09E570"
    assert _identifier_for_previous_release(
        "seasonal",
        season_index=9,
        identifier="ep-extra.other.S06E570.10",
    ) == "ep-extra.S09E570.10"



def test_episode_read_view_derives_identifier_fields_during_model_validation():
    from backend.api.models.episode import EpisodeAPIReadView

    view = EpisodeAPIReadView.model_validate(
        {
            "id": 1,
            "source_key": "dailywire",
            "collection_id": 2,
            "season_id": 3,
            "index": 4,
            "episode_identifier": "ep-extra.other.S03E42.10",
            "source_number": "42.10",
            "publish_status": "published_final",
            "title": "Episode",
            "duration": 0,
            "slug": "episode",
            "thumbnail_landscape_path": None,
            "thumbnail_portrait_path": None,
            "thumbnail_square_path": None,
        }
    )

    assert view.episode_type == "ep-extra"
    assert view.episode_extra_type == "other"
    assert view.episode_number == "42"
    assert view.episode_sub_number == "10"
    assert view.episode_label == "S03E42.10"


def test_compact_episode_view_includes_identifier_semantics():
    import backend.db.models  # noqa: F401
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from backend.api.endpoints.episodes.service import get_episode_views_by_collection_page
    from backend.db import Base
    from backend.db.models import Episode, Season, Collection
    from backend.types.collection_types import EpisodeIdentifier, CollectionType

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)

    collection = Collection(
        source_key="dailywire",
        uuid="collection-view-semantics",
        slug="view-semantics",
        title="View Semantics",
        description=None,
        sharing_url="https://example.test/collection",
        membership_level="FREE",
        type=CollectionType.SERIES.value,
        episode_identifier=EpisodeIdentifier.SEASONAL.value,
        author_name="Host",
        author_slug="host",
    )
    season = Season(
        collection=collection,
        index=3,
        slug="season-3",
        name="Season 3",
        season_type="normal",
        season_number=3,
    )
    episode = Episode(
        source_key="dailywire",
        uuid="episode-view-semantics",
        type="episode",
        collection=collection,
        season=season,
        index=12,
        episode_identifier="ep-extra.trailer.S03E12.5",
        source_number="12.05",
        slug="season-3-episode-12-trailer",
        title="Episode 12 Trailer",
        description=None,
        duration=60,
        publish_status="published_final",
        sharing_url="https://example.test/episode",
        published_date=datetime(2026, 9, 18, 12, 0, 0, tzinfo=timezone.utc),
    )
    session.add_all([collection, season, episode])
    session.commit()

    [view] = get_episode_views_by_collection_page(session, collection.slug, cursor=None, limit=10).items

    assert view.source_number == "12.05"
    assert view.episode_type == "ep-extra"
    assert view.episode_extra_type == "trailer"
    assert view.episode_number == "12"
    assert view.episode_sub_number == "5"
    assert view.episode_label == "S03E12.5"

    session.close()
    engine.dispose()
