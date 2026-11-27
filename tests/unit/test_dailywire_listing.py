"""The Daily Wire lists a show's episodes through its Source, as every Source does (``Source.list_episodes``)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

_OLD = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _record(slug: str, number: str = "1.00", *, title: str | None = None, is_trailer: bool | None = False, published=_OLD):
    from sources.dailywire.api.records import DwEpisodeRecord

    return DwEpisodeRecord(
        dw_id=f"remote-{slug}", slug=slug, title=title or slug, description=None, duration=3600,
        episode_number=number, display_episode_number="", background_image_path=None,
        sharing_url=f"https://www.dailywire.com/episode/{slug}", publish_status="PUBLISHED", is_downloadable=True,
        is_trailer=is_trailer, available_for=[], thumbnail_landscape_path=None, thumbnail_portrait_path=None,
        thumbnail_square_path=None, published_date=published, scheduled_date=None,
    )


def _detail(record, **changes):
    from sources.dailywire.api.records import DwEpisodeDetailRecord

    return DwEpisodeDetailRecord(**{
        **record.model_dump(mode="python", by_alias=False), "audio_url": "", "video_url": "https://stream.test/video.m3u8", "delivery_mode": "",
        "progress": 0.0, "next_episode_url": None, **changes,
    })


class _FakeClient:
    """The Daily Wire's API with one page per season, newest first when asked so."""

    def __init__(self, seasons: dict[str, list], details: dict | None = None, pages: dict[str, list[list]] | None = None):
        self.seasons, self.details, self.pages = seasons, details or {}, pages or {}
        self.detail_calls: list[str] = []
        self.page_calls: list[str] = []

    def get_show_page(self, slug, *, membership_plan=None):
        return SimpleNamespace(
            author_name="Host", seasons=[SimpleNamespace(slug=slug_, name=slug_, dw_id=slug_) for slug_ in self.seasons],
        )

    def get_episodes_paginated(self, _slug, selector):
        from sources.dailywire.api.dw_api.client import ByNextPage, EpisodesPaginatedResult

        if isinstance(selector, ByNextPage):
            season, _, page = selector.next_page_url.rpartition("/")
            page = int(page)
        else:
            season, page = selector.season_dw_id, 0
        self.page_calls.append(f"{season}/{page}")
        pages = self.pages.get(season) or [self.seasons[season]]
        if not isinstance(selector, ByNextPage) and selector.order_by == "CreatedAt_ASC":
            pages = [list(reversed(items)) for items in reversed(pages)]
        more = page + 1 < len(pages)
        return EpisodesPaginatedResult(pages[page], f"{season}/{page + 1}" if more else None, more)

    def get_episode_details(self, slug, *, require_member_exclusive=False):
        self.detail_calls.append(slug)
        return self.details[slug]


@pytest.fixture
def listing(monkeypatch):
    from sources.dailywire import source as module, status

    # Each recording the details point to is an hour long.
    monkeypatch.setattr(status, "stream_length", lambda _url: 3600.0)

    def listing(client, *, known=frozenset(), membership=None):
        monkeypatch.setattr(module, "MiddlewareClient", lambda **_kwargs: client)
        monkeypatch.setattr(module, "_access_token", lambda: None)
        return list(module.DailyWireSource().list_episodes(
            "https://www.dailywire.com/show/the-show", known=known, membership=membership,
        ))

    return listing


def test_a_whole_listing_trusts_old_episodes_and_numbers_its_seasons_oldest_first(listing):
    client = _FakeClient({"2025": [_record("b", "2.00"), _record("a", "1.00")], "2026": [_record("c", "3.01")]})

    found = listing(client)

    assert [(video.slug, video.season.number, video.episode_number, video.extra_number, video.tag) for video in found] == [
        ("c", 2, 3, 1, "ep-extra"), ("a", 1, 1, None, "ep"), ("b", 1, 2, None, "ep"),
    ]
    assert all(video.author_name == "Host" for video in found)
    assert client.detail_calls == []


def test_an_ambiguous_trailer_title_is_checked_in_its_details(listing):
    record = _record("reacting-to-a-trailer", "2083.05", title="Reacting To A Movie Trailer", is_trailer=None)
    client = _FakeClient({"2026": [record]}, details={record.slug: _detail(record, is_trailer=True)})

    [video] = listing(client)

    assert client.detail_calls == [record.slug]
    assert (video.tag, video.extra_number) == ("trailer", 5)


@pytest.mark.parametrize("record", [
    _record("flagged", "2083.05", title="Movie Trailer", is_trailer=True),
    _record("official", "2083.00", title="Official Trailer", is_trailer=False),
])
def test_a_trailer_the_listing_already_tells_is_not_looked_up(listing, record):
    client = _FakeClient({"2026": [record]})

    [video] = listing(client)

    assert client.detail_calls == []
    assert video.tag == "trailer"


def test_a_new_listing_stops_at_the_first_episode_out_for_good_and_looks_up_what_is_new(listing):
    new = [_record("new-2", "12.00"), _record("new-1", "11.00")]
    client = _FakeClient(
        {"2025": [_record("older", "1.00")], "2026": []},
        details={record.slug: _detail(record) for record in new},
        pages={"2026": [new, [_record("known", "10.00"), _record("old", "9.00")], [_record("oldest", "8.00")]]},
    )

    found = listing(client, known=frozenset({"known", "old", "older"}))

    assert [video.slug for video in found] == ["new-2", "new-1"]
    assert client.page_calls == ["2026/0", "2026/1"]
    assert sorted(client.detail_calls) == ["new-1", "new-2"]


def test_a_new_episode_with_nothing_usable_is_left_out(listing):
    placeholder = _record("show-no-show-today", "13.00")
    processing = _record("processing", "14.00", published=datetime.now(timezone.utc) - timedelta(minutes=5))
    client = _FakeClient(
        {"2026": [processing, placeholder, _record("known", "10.00")]},
        details={processing.slug: _detail(processing, duration=0, video_url="")},
    )

    assert listing(client, known=frozenset({"known"})) == []


def test_members_only_shows_are_listed_only_when_signed_in(listing):
    client = _FakeClient({"2026": [_record("a")]})

    assert listing(client, membership="INSIDER") == []
    assert client.page_calls == []
