from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column

PICTURE_PATH_COMMENT = (
    "A picture: the web address of an image at its Source, "
    "or thumbnails/<name>.jpg for an image VODLoft made itself and keeps in its thumbnail folder"
)

class MediaContentMetadataMixin:
    """Reusable intrinsic media metadata stored by the content owner.

    MediaItemBase deliberately does not inherit this mixin: a media item models
    VODLoft identity/placement and download state, while the concrete content
    owner decides where these descriptive fields live. Episodes and movies own
    them directly; shared movie-extra sources own them for all of their placements.
    """

    title: Mapped[str] = mapped_column(default="", server_default="")
    description: Mapped[Optional[str]]
    duration: Mapped[float] = mapped_column(default=0.0, server_default="0")
    background_image_path: Mapped[Optional[str]] = mapped_column(comment=PICTURE_PATH_COMMENT)
    thumbnail_landscape_path: Mapped[Optional[str]] = mapped_column(comment=PICTURE_PATH_COMMENT)
    thumbnail_portrait_path: Mapped[Optional[str]] = mapped_column(comment=PICTURE_PATH_COMMENT)
    thumbnail_square_path: Mapped[Optional[str]] = mapped_column(comment=PICTURE_PATH_COMMENT)
