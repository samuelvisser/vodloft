"""Normalized Source independent media identity and local representations."""

from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, JSON, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.core import Base


def now() -> datetime:
    return datetime.now(timezone.utc)


class Domain(Base):
    __tablename__ = "vodloft_domains"
    id: Mapped[int] = mapped_column(primary_key=True)
    hostname: Mapped[str] = mapped_column(String, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String)


class SourceDomain(Base):
    __tablename__ = "vodloft_source_domains"
    __table_args__ = (UniqueConstraint("source_id", "domain_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[str] = mapped_column(String)
    domain_id: Mapped[int] = mapped_column(ForeignKey("vodloft_domains.id"))
    support: Mapped[str] = mapped_column(String(20), default="verified")


class SourceConnection(Base):
    __tablename__ = "vodloft_source_connections"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    secret_references: Mapped[dict] = mapped_column(JSON, default=dict)
    authentication_reference: Mapped[str | None] = mapped_column(String(64), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class MediaItem(Base):
    __tablename__ = "vodloft_media_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("vodloft_domains.id"))
    kind: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    duration: Mapped[float | None] = mapped_column(nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    capabilities: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    is_live: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    formats: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    normalized_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    user_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    artwork_url: Mapped[str | None] = mapped_column(String, nullable=True)
    user_title: Mapped[str | None] = mapped_column(String, nullable=True)
    user_description: Mapped[str | None] = mapped_column(String, nullable=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("vodloft_media_items.id"), nullable=True)
    extra_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SourceReference(Base):
    __tablename__ = "vodloft_source_references"
    __table_args__ = (UniqueConstraint("source_id", "domain_id", "namespace", "upstream_id", "connection_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("vodloft_media_items.id", ondelete="CASCADE"))
    domain_id: Mapped[int] = mapped_column(ForeignKey("vodloft_domains.id"))
    source_id: Mapped[str] = mapped_column(String)
    namespace: Mapped[str] = mapped_column(String)
    upstream_id: Mapped[str] = mapped_column(String)
    url: Mapped[str] = mapped_column(String)
    connection_id: Mapped[int | None] = mapped_column(ForeignKey("vodloft_source_connections.id"), nullable=True)
    connection_key: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class SourceSnapshot(Base):
    """Prior upstream metadata for a scoped repair after a faulty Source update."""
    __tablename__ = "vodloft_source_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("vodloft_media_items.id", ondelete="CASCADE"))
    source_id: Mapped[str] = mapped_column(String)
    connection_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    runtime_version: Mapped[str] = mapped_column(String)
    metadata_snapshot: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CollectionEntry(Base):
    __tablename__ = "vodloft_collection_entries"
    __table_args__ = (UniqueConstraint("collection_id", "occurrence_key", name="uq_vodloft_collection_entry_occurrence"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    collection_id: Mapped[int] = mapped_column(ForeignKey("vodloft_media_items.id", ondelete="CASCADE"))
    item_id: Mapped[int] = mapped_column(ForeignKey("vodloft_media_items.id", ondelete="CASCADE"))
    occurrence_key: Mapped[str | None] = mapped_column(String, nullable=True)
    position: Mapped[int] = mapped_column(Integer)
    group: Mapped[str | None] = mapped_column(String, nullable=True)
    episode_number: Mapped[str | None] = mapped_column(String, nullable=True)
    role: Mapped[str | None] = mapped_column(String(32), nullable=True)


class LegacyMediaLink(Base):
    __tablename__ = "vodloft_legacy_media_links"
    __table_args__ = (UniqueConstraint("legacy_type", "legacy_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    legacy_type: Mapped[str] = mapped_column(String(24))
    legacy_id: Mapped[int] = mapped_column(Integer)
    item_id: Mapped[int] = mapped_column(ForeignKey("vodloft_media_items.id", ondelete="CASCADE"))


class MovieExtraParent(Base):
    __tablename__ = "vodloft_movie_extra_parents"
    __table_args__ = (UniqueConstraint("movie_id", "extra_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    movie_id: Mapped[int] = mapped_column(ForeignKey("vodloft_media_items.id", ondelete="CASCADE"))
    extra_id: Mapped[int] = mapped_column(ForeignKey("vodloft_media_items.id", ondelete="CASCADE"))
    extra_type: Mapped[str] = mapped_column(String(32))


class CollectionDownloadProfile(Base):
    __tablename__ = "vodloft_collection_download_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    collection_id: Mapped[int] = mapped_column(ForeignKey("vodloft_media_items.id", ondelete="CASCADE"))
    source_reference_id: Mapped[int | None] = mapped_column(ForeignKey("vodloft_source_references.id"), nullable=True)
    name: Mapped[str] = mapped_column(String)
    local_profile_ids: Mapped[list[int]] = mapped_column(JSON)
    backfill: Mapped[str] = mapped_column(String(24), default="newest")
    newest_count: Mapped[int] = mapped_column(Integer, default=10)
    published_after: Mapped[date | None] = mapped_column(Date, nullable=True)
    published_before: Mapped[date | None] = mapped_column(Date, nullable=True)
    title_contains: Mapped[str | None] = mapped_column(String(200), nullable=True)
    selected_groups: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    known_groups: Mapped[list[str]] = mapped_column(JSON, default=list)
    include_future_groups: Mapped[bool] = mapped_column(Boolean, default=True)
    member_roles: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    refresh_minutes: Mapped[int] = mapped_column(Integer, default=60)
    retain_newest: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retain_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CollectionScan(Base):
    __tablename__ = "vodloft_collection_scans"
    id: Mapped[int] = mapped_column(primary_key=True)
    collection_id: Mapped[int] = mapped_column(ForeignKey("vodloft_media_items.id", ondelete="CASCADE"))
    source_id: Mapped[str] = mapped_column(String)
    runtime_version: Mapped[str | None] = mapped_column(String, nullable=True)
    connection_id: Mapped[int | None] = mapped_column(ForeignKey("vodloft_source_connections.id"), nullable=True)
    next_cursor: Mapped[str | None] = mapped_column(String, nullable=True)
    complete: Mapped[bool] = mapped_column(Boolean)
    entry_count: Mapped[int] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CollectionStreamProfile(Base):
    __tablename__ = "vodloft_collection_stream_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    collection_id: Mapped[int] = mapped_column(ForeignKey("vodloft_media_items.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String)
    format: Mapped[str] = mapped_column(String(16), default="audio")
    published_after: Mapped[date | None] = mapped_column(Date, nullable=True)
    published_before: Mapped[date | None] = mapped_column(Date, nullable=True)
    title_contains: Mapped[str | None] = mapped_column(String(200), nullable=True)
    selected_groups: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    known_groups: Mapped[list[str]] = mapped_column(JSON, default=list)
    include_future_groups: Mapped[bool] = mapped_column(Boolean, default=True)
    member_roles: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    max_items: Mapped[int] = mapped_column(Integer, default=0)
    feed_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    allow_other_renditions: Mapped[bool] = mapped_column(Boolean, default=False)
    source_reference_id: Mapped[int | None] = mapped_column(ForeignKey('vodloft_source_references.id'), nullable=True)
    local_profile_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    refresh_minutes: Mapped[int] = mapped_column(Integer, default=60)
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    local_only: Mapped[bool] = mapped_column(Boolean, default=True)
    include_live: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class LiveAdmission(Base):
    """An admitted live item survives its upstream live-to-archive transition."""
    __tablename__ = "vodloft_live_admissions"
    __table_args__ = (UniqueConstraint("stream_profile_id", "item_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    stream_profile_id: Mapped[int] = mapped_column(ForeignKey(
        "vodloft_collection_stream_profiles.id", ondelete="CASCADE"))
    item_id: Mapped[int] = mapped_column(ForeignKey("vodloft_media_items.id", ondelete="CASCADE"))
    source_reference_id: Mapped[int] = mapped_column(ForeignKey("vodloft_source_references.id"))
    state: Mapped[str] = mapped_column(String(24), default="upstream")
    admitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Artifact(Base):
    __tablename__ = "vodloft_artifacts"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("vodloft_media_items.id", ondelete="CASCADE"))
    profile_id: Mapped[int | None] = mapped_column(ForeignKey("local_media_profiles.id"), nullable=True)
    source_reference_id: Mapped[int | None] = mapped_column(ForeignKey("vodloft_source_references.id"), nullable=True)
    representation_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    path: Mapped[str] = mapped_column(String, unique=True)
    size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AcquisitionJob(Base):
    __tablename__ = "vodloft_acquisition_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("vodloft_media_items.id", ondelete="CASCADE"))
    reference_id: Mapped[int] = mapped_column(ForeignKey("vodloft_source_references.id"))
    operation_id: Mapped[str | None] = mapped_column(ForeignKey("task_operations.id"), nullable=True)
    profile_id: Mapped[int | None] = mapped_column(ForeignKey("local_media_profiles.id"), nullable=True)
    execution_spec: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    active_key: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    lease_owner: Mapped[str | None] = mapped_column(String(40), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    state: Mapped[str] = mapped_column(String(32), default="queued")
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    failed_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class FileFinalization(Base):
    __tablename__ = "vodloft_file_finalizations"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("vodloft_acquisition_jobs.id", ondelete="CASCADE"), unique=True)
    destination: Mapped[str] = mapped_column(String)
    placement_path: Mapped[str | None] = mapped_column(String, nullable=True)
    previous_artifact_id: Mapped[int | None] = mapped_column(ForeignKey("vodloft_artifacts.id"), nullable=True)
    phase: Mapped[str] = mapped_column(String(24), default="prepared")


class ArtifactPlacement(Base):
    __tablename__ = "vodloft_artifact_placements"
    id: Mapped[int] = mapped_column(primary_key=True)
    artifact_id: Mapped[int] = mapped_column(ForeignKey("vodloft_artifacts.id", ondelete="CASCADE"))
    profile_id: Mapped[int] = mapped_column(ForeignKey("local_media_profiles.id"))
    path: Mapped[str] = mapped_column(String, unique=True)


class MediaDemand(Base):
    """A durable reason to keep a particular item/profile representation."""
    __tablename__ = "vodloft_media_demands"
    __table_args__ = (UniqueConstraint("item_id", "profile_id", "owner_kind", "owner_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("vodloft_media_items.id", ondelete="CASCADE"))
    profile_id: Mapped[int] = mapped_column(ForeignKey("local_media_profiles.id"))
    owner_kind: Mapped[str] = mapped_column(String(24))
    owner_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class MediaSuppression(Base):
    __tablename__ = "vodloft_media_suppressions"
    __table_args__ = (UniqueConstraint("item_id", "profile_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("vodloft_media_items.id", ondelete="CASCADE"))
    profile_id: Mapped[int] = mapped_column(ForeignKey("local_media_profiles.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class MediaServerTarget(Base):
    __tablename__ = "vodloft_media_server_targets"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(24))
    name: Mapped[str] = mapped_column(String)
    base_url: Mapped[str] = mapped_column(String)
    library_id: Mapped[str] = mapped_column(String)
    local_prefix: Mapped[str] = mapped_column(String)
    server_prefix: Mapped[str] = mapped_column(String)
    secret_ciphertext: Mapped[str] = mapped_column(String)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class MediaServerExport(Base):
    __tablename__ = "vodloft_media_server_exports"
    __table_args__ = (UniqueConstraint("placement_id", "target_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    placement_id: Mapped[int] = mapped_column(ForeignKey("vodloft_artifact_placements.id", ondelete="CASCADE"))
    target_id: Mapped[int] = mapped_column(ForeignKey("vodloft_media_server_targets.id"))
    remote_id: Mapped[str | None] = mapped_column(String, nullable=True)
    remote_episode_id: Mapped[str | None] = mapped_column(String, nullable=True)
    remote_server_id: Mapped[str | None] = mapped_column(String, nullable=True)
    presentation_strategy: Mapped[str | None] = mapped_column(String(32), nullable=True)
    season_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    episode_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    state: Mapped[str] = mapped_column(String(24), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class FeedSubscription(Base):
    __tablename__ = "vodloft_feed_subscriptions"
    __table_args__ = (UniqueConstraint("stream_profile_id", "user_key", name="uq_vodloft_feed_profile_user"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    collection_id: Mapped[int] = mapped_column(ForeignKey("vodloft_media_items.id", ondelete="CASCADE"))
    stream_profile_id: Mapped[int | None] = mapped_column(ForeignKey("vodloft_collection_stream_profiles.id"), nullable=True)
    user_key: Mapped[str] = mapped_column(String(80), default="admin", server_default="admin")
    integration_target_id: Mapped[int | None] = mapped_column(ForeignKey("vodloft_media_server_targets.id"), nullable=True)
    token: Mapped[str] = mapped_column(String(64), unique=True)


class PublishedEntry(Base):
    __tablename__ = "vodloft_published_entries"
    __table_args__ = (UniqueConstraint("subscription_id", "item_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("vodloft_feed_subscriptions.id", ondelete="CASCADE"))
    item_id: Mapped[int] = mapped_column(ForeignKey("vodloft_media_items.id", ondelete="CASCADE"))
    path: Mapped[str] = mapped_column(String, unique=True)
    size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PlaybackProgress(Base):
    __tablename__ = "vodloft_playback_progress"
    __table_args__ = (UniqueConstraint("user_key", "item_id", name="uq_vodloft_playback_user_item"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_key: Mapped[str] = mapped_column(String(80), default="admin")
    item_id: Mapped[int] = mapped_column(ForeignKey("vodloft_media_items.id", ondelete="CASCADE"))
    seconds: Mapped[float] = mapped_column(default=0.0)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class PlaybackSession(Base):
    """One web session remains bound to one local or upstream representation."""
    __tablename__ = "vodloft_playback_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_key: Mapped[str] = mapped_column(String(80), default="admin", server_default="admin")
    item_id: Mapped[int] = mapped_column(ForeignKey("vodloft_media_items.id", ondelete="CASCADE"))
    source_id: Mapped[str] = mapped_column(String(64))
    reference_id: Mapped[int | None] = mapped_column(ForeignKey("vodloft_source_references.id"), nullable=True)
    transport: Mapped[str] = mapped_column(String(16))
    lease_ciphertext: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PlaybackSegment(Base):
    __tablename__ = "vodloft_playback_segments"
    __table_args__ = (UniqueConstraint("session_id", "public_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("vodloft_playback_sessions.id", ondelete="CASCADE"))
    public_id: Mapped[str] = mapped_column(String(40))
    url_ciphertext: Mapped[str] = mapped_column(String)


class LocalUser(Base):
    __tablename__ = "vodloft_users"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String(16), default="member")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    can_subscribe: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_approve: Mapped[bool] = mapped_column(Boolean, default=False)
    request_quota: Mapped[int] = mapped_column(Integer, default=10)
    connection_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    target_ids: Mapped[list[int]] = mapped_column(JSON, default=list)


class LibraryRequest(Base):
    """User demand exists independently from the acquisition job it may cause."""
    __tablename__ = "vodloft_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_key: Mapped[str] = mapped_column(String(80), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("vodloft_media_items.id", ondelete="CASCADE"))
    profile_id: Mapped[int] = mapped_column(ForeignKey("local_media_profiles.id"))
    reference_id: Mapped[int | None] = mapped_column(ForeignKey("vodloft_source_references.id"), nullable=True)
    state: Mapped[str] = mapped_column(String(24), default="pending")
    job_id: Mapped[int | None] = mapped_column(ForeignKey("vodloft_acquisition_jobs.id", ondelete="SET NULL"), nullable=True)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    active_key: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class IntegrationUserMapping(Base):
    __tablename__ = "vodloft_integration_user_mappings"
    __table_args__ = (UniqueConstraint("target_id", "user_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    target_id: Mapped[int] = mapped_column(ForeignKey("vodloft_media_server_targets.id"))
    user_key: Mapped[str] = mapped_column(String(80))
    remote_user_id: Mapped[str] = mapped_column(String(120))
    secret_ciphertext: Mapped[str] = mapped_column(String)


class IntegrationFeedDelivery(Base):
    __tablename__ = "vodloft_integration_feed_deliveries"
    __table_args__ = (UniqueConstraint("target_id", "subscription_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    target_id: Mapped[int] = mapped_column(ForeignKey("vodloft_media_server_targets.id"))
    subscription_id: Mapped[int] = mapped_column(ForeignKey("vodloft_feed_subscriptions.id", ondelete="CASCADE"))
    folder_id: Mapped[str] = mapped_column(String(120))
    server_path: Mapped[str] = mapped_column(String)
    feed_url: Mapped[str] = mapped_column(String)
    remote_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    state: Mapped[str] = mapped_column(String(24), default="pending")
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IntegrationFeedItem(Base):
    __tablename__ = "vodloft_integration_feed_items"
    __table_args__ = (UniqueConstraint("delivery_id", "item_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    delivery_id: Mapped[int] = mapped_column(ForeignKey("vodloft_integration_feed_deliveries.id", ondelete="CASCADE"))
    item_id: Mapped[int] = mapped_column(ForeignKey("vodloft_media_items.id", ondelete="CASCADE"))
    remote_episode_id: Mapped[str] = mapped_column(String(120))
    available: Mapped[bool] = mapped_column(Boolean, default=False)
