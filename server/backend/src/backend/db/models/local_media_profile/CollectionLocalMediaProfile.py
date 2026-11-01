from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from backend.db.mixins.HasMetadataMixin import HasMetadataMixin

from backend.types.local_media_profile_types import LocalMediaProfileType, CollectionLocalMediaProfileScope

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

    @property
    def indexing_values(self):
        from backend.utils.custom_index import get_indexing_value_definitions
        return get_indexing_value_definitions(self)
