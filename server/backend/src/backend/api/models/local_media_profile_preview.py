from typing import Literal

from pydantic import Field

from backend.api.models.base import ResponseBase
from backend.utils.metadata_template import DESCRIPTION_TEMPLATE_MAX_LENGTH, TITLE_TEMPLATE_MAX_LENGTH
from backend.api.models.local_media_profile import (
    LocalMediaProfileTemplatePreview,
    LocalMediaProfileTemplatePreviewResult,
)


class LocalMediaProfilePreviewRequest(LocalMediaProfileTemplatePreview):
    """One unsaved profile and editable example shared by every form preview."""

    type: Literal["collection", "video"]
    source_id: str | None = Field(default=None, max_length=100)
    local_media_profile_id: int | None = Field(default=None, gt=0)
    episode_title_template: str | None = Field(default=None, max_length=TITLE_TEMPLATE_MAX_LENGTH)
    episode_description_template: str | None = Field(default=None, max_length=DESCRIPTION_TEMPLATE_MAX_LENGTH)


class LocalMediaProfilePreviewPlan(ResponseBase):
    simulates_custom_indexes: bool
    reason: str | None = None


class LocalMediaProfileOutputPreview(LocalMediaProfileTemplatePreviewResult):
    output_path: str | None = None
    used_variables: list[str] = Field(default_factory=list)
    error: str | None = None


class LocalMediaProfileCollectionPreview(ResponseBase):
    path: str | None = None
    reason: str | None = None
    collection_title: str | None = None
    system_enabled: bool


class LocalMediaProfileMetadataPreview(ResponseBase):
    """The title and description an episode's metadata gets, and why a template could not render."""

    title: str
    title_error: str | None = None
    description: str
    description_error: str | None = None


class LocalMediaProfilePreviewResult(ResponseBase):
    output: LocalMediaProfileOutputPreview
    collection_root: LocalMediaProfileCollectionPreview | None = None
    metadata: LocalMediaProfileMetadataPreview | None = None
