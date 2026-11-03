from __future__ import annotations

from datetime import datetime, timezone

from sources.dailywire.api.records import DwShowRecord


def _show_page(*, seasons):
    return {
        "show": {
            "id": "show-1",
            "slug": "yes-or-no",
            "title": "Yes or No",
            "sharingURL": "https://www.dailywire.com/show/yes-or-no",
            "seasons": seasons,
            "latestEpisode": {
                "id": "episode-1",
                "slug": "episode-1",
                "title": "Episode 1",
                "duration": 60,
                "sharingURL": "https://www.dailywire.com/episode/episode-1",
                "status": "published",
                "isDownloadable": True,
                "publishedAt": datetime(2026, 9, 22, tzinfo=timezone.utc),
            },
        },
        "selectedSeason": {"id": "season-1", "name": "Season 1", "slug": "season-1"},
    }


def test_show_suggests_collection_type_under_the_name_the_add_collection_form_reads():
    record = DwShowRecord.model_validate(_show_page(seasons=[{"id": "season-1", "name": "Season 1", "slug": "season-1"}]))

    data = record.model_dump(mode="json")

    assert data["probableCollectionType"] == "series"
    assert data["probableEpisodeIdentification"] == "numbered"


def test_show_with_year_seasons_suggests_a_podcast():
    record = DwShowRecord.model_validate(_show_page(seasons=[{"id": "season-1", "name": "2026", "slug": "2026"}]))

    assert record.model_dump(mode="json")["probableCollectionType"] == "podcast"
