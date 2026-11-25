"""A feed of a creator's on a yt-dlp site, which yt-dlp reads from its own page of the creator's."""
from __future__ import annotations

from dataclasses import dataclass

from ...contract import MAIN_TAG, Names, SectionKind, SectionRole, SectionType


@dataclass(frozen=True, init=False)
class YtdlpFeedSectionType(SectionType):
    """A type of feed, such as YouTube's Shorts, with ``path``, the page of the creator's that yt-dlp lists it from,
    such as ``shorts`` for ``youtube.com/@creator/shorts``. Every yt-dlp site reads its feeds by their path, so a
    site's contract alone says which feeds it has."""

    path: str

    def __init__(
        self, key: str, names: Names, path: str, role: SectionRole = SectionRole.MAIN, episode_tag: str = MAIN_TAG,
    ) -> None:
        super().__init__(key, SectionKind.FEED, names, role=role, episode_tag=episode_tag)
        object.__setattr__(self, "path", path)

    @property
    def feed_ref(self) -> str:
        """yt-dlp names a creator's feed by its page."""
        return self.path
