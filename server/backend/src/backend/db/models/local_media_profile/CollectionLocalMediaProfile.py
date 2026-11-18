from sqlalchemy import ForeignKey, String, Text, false
from sqlalchemy.orm import Mapped, mapped_column
from backend.db.mixins.HasMetadataMixin import HasMetadataMixin

from backend.types.local_media_profile_types import CollectionLocalMediaProfileScope, EpisodeNfo, LocalMediaProfileType

from .LocalMediaProfileBase import LocalMediaProfileBase


class CollectionLocalMediaProfile(LocalMediaProfileBase, HasMetadataMixin):
    __tablename__ = "local_media_profiles_collection"
    __metadata_parent_table__ = "local_media_profiles"
    __mapper_args__ = {"polymorphic_identity": LocalMediaProfileType.COLLECTION.value}

    id: Mapped[int] = mapped_column(
        ForeignKey("local_media_profiles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    collection_scope: Mapped[str] = mapped_column(
        default=CollectionLocalMediaProfileScope.BOTH.value,
        server_default=CollectionLocalMediaProfileScope.BOTH.value,
        nullable=False,
    )

    # None inherits the system default; explicit booleans override it.
    download_collection_assets: Mapped[bool | None] = mapped_column(nullable=True)
    show_nfo: Mapped[bool] = mapped_column(
        default=False, server_default=false(), nullable=False,
        comment="Write tvshow.nfo in the collection's folder and season.nfo in each season's folder",
    )
    episode_nfo: Mapped[str] = mapped_column(
        String(16), default=EpisodeNfo.EPISODE.value, server_default=EpisodeNfo.EPISODE.value, nullable=False,
        comment="What each episode's NFO file and embedded metadata call it: episode or music_video",
    )
    episode_title_template: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="A Jinja template for each episode's title in its NFO and embedded metadata",
    )
    episode_description_template: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="A Jinja template for each episode's description in its NFO and embedded metadata",
    )

    @property
    def indexing_values(self):
        from backend.utils.custom_index import get_indexing_value_definitions
        return get_indexing_value_definitions(self)


class MusicLocalMediaProfile(CollectionLocalMediaProfile):
    """A Collection profile that keeps episodes as music: an audio file per track, tagged with the artist, the
    album (the episode's season) and the track number. It shares the Collection profile's table."""

    __mapper_args__ = {"polymorphic_identity": LocalMediaProfileType.MUSIC.value}
