"""Any of a creator's collections can gather several of its feeds and lists, not only the creator's own collection: a
feed or list goes into the one the user picks, and a collection made from one feed or list keeps that one as it is."""
from __future__ import annotations

from sqlalchemy import select

from test_creators import ROOT, client, tube  # noqa: F401
from test_reassigned import _cabin_video, _episode, _settled, creator  # noqa: F401
from test_section_moves import feeds  # noqa: F401
from test_ytdlp_collections import session  # noqa: F401


def _move(client, ref, target, collection=None):
    _settled()
    move = {"accountId": 1, "ref": ref, "target": target, **({"collectionSlug": collection} if collection else {})}
    return client.patch("/api/creators/workshop", json={"moves": [move]})


def _sections(page):
    return {section["ref"]: section for section in page["accounts"][0]["sections"]}


def _collection(session, slug):
    from backend.db.models import Collection

    session.expire_all()
    return session.scalar(select(Collection).where(Collection.slug == slug))


def test_livestreams_join_the_shorts_collection_with_their_files(feeds, client, session):
    from backend.db.models.media_download import EpisodeMediaDownload
    from backend.services.link_seasons import own_feeds, own_link

    assert _move(client, "shorts", "own").status_code == 200
    page = client.get("/api/creators/workshop").json()
    assert page["accounts"][0]["gatherableSlugs"] == ["UCworkshop", "UCworkshop-shorts"]
    l1 = _episode(session, feeds, "l1")
    download_id = l1.downloads[0].id

    _settled()
    preview = client.post("/api/creators/workshop/moves/preview", json={"moves": [
        {"accountId": 1, "ref": "streams", "target": "main", "collectionSlug": "UCworkshop-shorts"},
    ]})
    assert preview.status_code == 200, preview.text
    assert {item["slug"]: item["state"] for item in preview.json()["collections"]} == {
        "UCworkshop": "existing", "UCworkshop-shorts": "existing",
    }

    moved = _move(client, "streams", "main", "UCworkshop-shorts")

    assert moved.status_code == 200, moved.text
    shorts = _collection(session, "UCworkshop-shorts")
    main = _collection(session, "UCworkshop")
    assert sorted(shorts.feeds) == ["shorts", "streams"] and sorted(main.feeds) == ["videos"]
    # It lists the creator's page now, and only its own feeds there.
    assert (own_link(shorts), own_feeds(shorts)) == ("https://tube.example/@workshop/videos", frozenset({"shorts", "streams"}))
    assert session.get(EpisodeMediaDownload, download_id).media.collection_id == shorts.id
    sections = _sections(moved.json())
    assert (sections["streams"]["collectionSlug"], sections["shorts"]["collectionSlug"]) == ("UCworkshop-shorts", "UCworkshop-shorts")
    assert moved.json()["accounts"][0]["gatheringSlugs"] == ["UCworkshop", "UCworkshop-shorts"]

    back = _move(client, "streams", "main")

    assert back.status_code == 200, back.text
    assert sorted(_collection(session, "UCworkshop").feeds) == ["streams", "videos"]
    assert _collection(session, "UCworkshop-shorts").feeds == ["shorts"]
    assert session.get(EpisodeMediaDownload, download_id).media.collection_id == main.id


def test_a_playlist_season_joins_the_collection_of_another_playlist_which_keeps_its_own(creator, client, session):
    from backend.db.core import run_write_transaction
    from backend.services.link_seasons import place_in_link_seasons

    main, tools = creator
    main_id, tools_id = main.id, tools.id
    _cabin_video(session, main)
    run_write_transaction(lambda w: place_in_link_seasons(w, w.get(type(main), main_id), with_files=True))
    tools_seasons = {episode.source_slug: episode.season.name for episode in _collection(session, "PLtools").episodes}

    moved = _move(client, "PLcabin", "main", "PLtools")

    assert moved.status_code == 200, moved.text
    tools = _collection(session, "PLtools")
    assert tools.id == tools_id and tools.creator_account_id is not None
    links = {link.ref: link for link in tools.lists if link.enabled}
    # Its own playlist stays as it was, not a season; the one that joined is a season.
    assert (links["PLtools"].as_season, links["PLcabin"].as_season) == (False, True)
    # c1 is in both playlists, and goes to the season; the others stay where they were.
    assert {episode.source_slug: episode.season.name for episode in tools.episodes if episode.source_slug in tools_seasons} == {
        **tools_seasons, "c1": "Building the Cabin",
    }
    assert _episode(session, tools, "k1").season.name == "Building the Cabin"
    assert _episode(session, _collection(session, "UCworkshop"), "k1") is None
    sections = _sections(moved.json())
    assert (sections["PLcabin"]["collectionSlug"], sections["PLcabin"]["asSeason"]) == ("PLtools", True)
    assert (sections["PLtools"]["collectionSlug"], sections["PLtools"]["asSeason"]) == ("PLtools", False)


def test_a_playlist_the_creator_has_not_placed_goes_into_the_collection_picked_for_it(feeds, client, session):
    assert _move(client, "shorts", "own").status_code == 200

    page = client.post("/api/creators/workshop/accounts/1/sections", json={"sections": [
        {"ref": "PLcabin", "target": "main_loose", "collectionSlug": "UCworkshop-shorts"},
    ]})

    assert page.status_code == 200, page.text
    shorts = _collection(session, "UCworkshop-shorts")
    assert {link.ref: link.as_season for link in shorts.lists if link.enabled} == {"PLcabin": False}
    assert _sections(page.json())["PLcabin"]["collectionSlug"] == "UCworkshop-shorts"


def test_the_videos_feed_stays_in_the_creators_own_collection(feeds, client):
    assert _move(client, "shorts", "own").status_code == 200

    refused = _move(client, "videos", "main", "UCworkshop-shorts")

    assert refused.status_code == 422 and "stays in it or leaves your library" in refused.text
    unknown = _move(client, "streams", "main", "nowhere")
    assert unknown.status_code == 422 and "can't go into that collection" in unknown.text


def test_the_feed_a_collection_was_made_from_stays_in_it_once_it_gathers_more(feeds, client):
    assert _move(client, "shorts", "own").status_code == 200
    assert _move(client, "streams", "main", "UCworkshop-shorts").status_code == 200

    refused = _move(client, "shorts", "own")

    assert refused.status_code == 422 and "was made from" in refused.text
