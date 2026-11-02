"""Development/demo data for ``backend-api db seed``.

Run it on a migrated database: the initial seed already created the default
Local Media Profiles, so the demo shows only add collections, seasons and episodes.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from backend.types.dailywire_user_info import DwMembershipLevel
from backend.types.episode_types import EpisodePublishStatus
from backend.types.media_types import MediaType
from backend.types.collection_types import EpisodeIdentifier, CollectionType
from backend.utils.helpers import slugify
from sources import DAILYWIRE


def _published(collection_index: int, episode_index: int) -> dt.datetime:
    """A stable, distinct publication instant per demo episode."""
    start = dt.datetime(2025, 1, 1, 12, tzinfo=dt.timezone.utc)
    return start + dt.timedelta(days=episode_index, minutes=collection_index)


def _collection(slug: str, title: str, author: str) -> dict[str, Any]:
    return {
        "uuid": f"demo-collection-{slug}",
        "source_key": DAILYWIRE,
        "slug": slug,
        "title": title,
        "description": None,
        "sharing_url": f"https://www.dailywire.com/show/{slug}",
        "membership_level": DwMembershipLevel.FREE.value,
        "type": CollectionType.PODCAST.value,
        "episode_identifier": EpisodeIdentifier.DATE_BASED.value,
        "author_name": author,
        "author_slug": slugify(author),
    }


collections: list[dict[str, Any]] = [
    _collection("the-ben-shapiro-show", "The Ben Shapiro Show", "Ben Shapiro"),
    _collection("the-matt-walsh-show", "The Matt Walsh Show", "Matt Walsh"),
    _collection("ben-after-dark", "Ben After Dark", "Ben Shapiro"),
]

# Number of demo episodes per collection, by collection slug.
episode_counts: dict[str, int] = {
    "the-ben-shapiro-show": 30,
    "the-matt-walsh-show": 20,
    "ben-after-dark": 7,
}


def episodes_for(collection: dict[str, Any], collection_index: int) -> list[dict[str, Any]]:
    """Demo episodes of one collection, oldest first, without collection and season ids."""
    episodes = []
    for index in range(1, episode_counts[collection["slug"]] + 1):
        published = _published(collection_index, index)
        episodes.append({
            "uuid": f"demo-episode-{collection['slug']}-{index}",
            "type": MediaType.EPISODE.value,
            "source_key": collection["source_key"],
            "index": index,
            "episode_identifier": f"ep.{published:%Y-%m-%dT%H:%M:%S.%f}",
            "slug": f"{collection['slug']}-{index}",
            "publish_status": EpisodePublishStatus.PUBLISHED_FINAL.value,
            "metadata_is_final": True,
            "sharing_url": f"{collection['sharing_url']}/episode-{index}",
            "published_date": published,
            "title": f"{collection['title']} — Episode {index}",
            "description": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
        })
    return episodes
