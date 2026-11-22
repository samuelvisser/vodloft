"""Collections on a Site whose videos have no title of their own name their episodes from the description."""
from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy import select

from sources import ItemRefresh, Site, VideoDetails, registry
from sources.contract import title_from_description
from sources.ytdlp.sites import site_of

from test_catalogue_refresh import RefreshingSource
from test_episode_details import _collection, factory  # noqa: F401
from test_ytdlp_collections import _video


@pytest.mark.parametrize(("description", "title"), [
    ("Sunset over the lake tonight\nShot on my phone", "Sunset over the lake tonight"),
    # Hashtags, mentions and links end it.
    ("Fingerboarding tricks with @cass.fb #skate", "Fingerboarding tricks with"),
    ("New recipe for pancakes https://example.com/recipe", "New recipe for pancakes"),
    # One within the first ten characters is part of it, so the title is never too short.
    ("@friend and I at the beach #summer", "@friend and I at the beach"),
    ("#jassmanak #lehanga #leenabhushan", "#jassmanak"),
    # At most 60 characters, ending at the last whole word.
    (
        "This is a very long first line that goes on and on about everything that happened today",
        "This is a very long first line that goes on and on about",
    ),
    # A first line too short goes on with the next one.
    ("\n  Part 2\nHow I built my cabin #diy", "Part 2 How I built my cabin"),
    # No dangling separators where it was cut.
    ("Big news for everyone - #announcement", "Big news for everyone"),
    # A single word longer than the most is cut at it.
    ("a" * 80, "a" * 60),
])
def test_a_title_is_the_first_line_of_the_description_up_to_a_hashtag_or_mention(description, title):
    assert title_from_description(description) == title


@pytest.mark.parametrize("description", [None, "", "  \n ", "Wow #fun", "#a #b #c"])
def test_a_description_with_too_little_makes_no_title(description):
    assert title_from_description(description) is None


def test_sites_without_titles_of_their_own_name_episodes_from_the_description():
    assert {key for key in ("instagram", "tiktok", "twitter", "youtube", "vimeo") if site_of(key).titles_from_description} == {
        "instagram", "tiktok", "twitter",
    }
    tiktok = site_of("tiktok")
    assert tiktok.episode_title("Video by someone", "My dog learned a new trick #dog") == "My dog learned a new trick"
    assert tiktok.episode_title("Video by someone", "#dog") == "Video by someone"
    assert site_of("youtube").episode_title("The real title", "Something else entirely") == "The real title"


_CAPTIONS = Site("captions", "Captions", ("listed.example",), titles_from_description=True)


class CaptionedSource(RefreshingSource):
    id = "captioned"

    def site_for(self, url):
        return _CAPTIONS


@pytest.fixture
def captioned(monkeypatch):
    monkeypatch.setattr(registry, "_sources", dict(registry._sources))
    return registry.register(CaptionedSource())


def _episode(session, collection_id):
    from backend.db.models import Episode

    return session.scalars(select(Episode).where(Episode.collection_id == collection_id)).one()


def test_a_collection_names_its_episodes_from_the_description_and_keeps_it_on_refresh(factory, captioned):  # noqa: F811
    from task_manager.tasks.helpers.listed_collections import add_listed_episodes, refresh_listed_collection

    with factory() as session:
        collection = _collection(session, "c1", "captioned")
        add_listed_episodes(session, collection_id=collection.id, found=[
            replace(_video("v1", 2024), title="Video by someone", description="Morning swim in the sea #summer"),
        ])
        session.commit()
        assert _episode(session, collection.id).title == "Morning swim in the sea"

        # A listing that tells no description keeps the title made from it.
        captioned.refresh = ItemRefresh(details={"v1": VideoDetails(slug="v1", url="u", title="Video by someone")})
        refresh_listed_collection(session, collection_id=collection.id, source=captioned)
        assert _episode(session, collection.id).title == "Morning swim in the sea"

        # A new description names it anew.
        captioned.refresh = ItemRefresh(details={"v1": VideoDetails(
            slug="v1", url="u", title="Video by someone", description="Evening swim in the sea @friend",
        )})
        refresh_listed_collection(session, collection_id=collection.id, source=captioned)
        assert _episode(session, collection.id).title == "Evening swim in the sea"


def test_a_single_video_keeps_the_sites_title(factory, captioned):  # noqa: F811
    from backend.db.models import Video
    from task_manager.tasks.helpers.refreshed_metadata import apply_refreshed_details

    video = Video(uuid="v", type="video", source_key="captioned", slug="v1", title="Old", sharing_url="https://listed.example/v1")

    apply_refreshed_details(video, VideoDetails(
        slug="v1", url="u", title="Video by someone", description="Morning swim in the sea #summer",
    ))

    assert video.title == "Video by someone"
