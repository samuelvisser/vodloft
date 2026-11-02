"""Create the schema VODLoft started from, the one WireLoft 1.2.3 left.

VODLoft was forked from WireLoft. This baseline replaces WireLoft's own
migrations (1.0 to 1.2.3), which now live in the importer and only run on an
uploaded copy of a WireLoft database. It creates the final 1.2.3 schema in one
step and keeps the revision id of WireLoft's last migration, so every VODLoft
database, which is already past it, upgrades exactly as before.

The statements are the schema SQLite holds after the old migrations ran,
statement for statement, so a fresh database gets the same tables, columns,
defaults, constraints and indexes. tests/unit/test_db_baseline.py compares the
two.

Revision ID: a4e7c19b2d53
Revises:
Create Date: 2026-11-02
"""
from __future__ import annotations

from alembic import op


revision = "a4e7c19b2d53"
down_revision = None
branch_labels = None
depends_on = None


_SCHEMA = (
    """
CREATE TABLE metadata (
    id INTEGER NOT NULL,
    parent_table VARCHAR NOT NULL,
    parent_id INTEGER NOT NULL,
    "key" VARCHAR NOT NULL,
    value VARCHAR NOT NULL,
    created_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
    updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
    CONSTRAINT pk_metadata PRIMARY KEY (id),
    CONSTRAINT uq_metadata_parent_key UNIQUE (parent_table, parent_id, "key")
)
""",
    """
CREATE INDEX ix_metadata_parent_id ON metadata (parent_id)
""",
    """
CREATE INDEX ix_metadata_parent ON metadata (parent_table, parent_id)
""",
    """
CREATE TABLE shows (
    id INTEGER NOT NULL,
    uuid VARCHAR NOT NULL,
    slug VARCHAR NOT NULL,
    title VARCHAR NOT NULL,
    description VARCHAR,
    sharing_url VARCHAR NOT NULL,
    membership_level VARCHAR NOT NULL,
    type VARCHAR NOT NULL,
    episode_identifier VARCHAR NOT NULL,
    author_name VARCHAR NOT NULL,
    author_slug VARCHAR NOT NULL,
    author_headshot_path VARCHAR,
    background_image_path VARCHAR,
    logo_image_path VARCHAR,
    thumbnail_landscape_path VARCHAR,
    thumbnail_portrait_path VARCHAR,
    thumbnail_square_path VARCHAR,
    created_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
    updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
    CONSTRAINT pk_shows PRIMARY KEY (id),
    CONSTRAINT uq_shows_sharing_url UNIQUE (sharing_url)
)
""",
    """
CREATE UNIQUE INDEX ix_shows_slug ON shows (slug)
""",
    """
CREATE UNIQUE INDEX ix_shows_uuid ON shows (uuid)
""",
    """
CREATE TABLE media_items (
    id INTEGER NOT NULL,
    uuid VARCHAR NOT NULL,
    type VARCHAR NOT NULL,
    created_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
    updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
    CONSTRAINT pk_media_items PRIMARY KEY (id)
)
""",
    """
CREATE UNIQUE INDEX ix_media_items_uuid ON media_items (uuid)
""",
    """
CREATE TABLE task_definitions (
    id INTEGER NOT NULL,
    "key" VARCHAR NOT NULL,
    title VARCHAR NOT NULL,
    description VARCHAR,
    allowed_resource_types JSON,
    default_max_retries INTEGER,
    CONSTRAINT pk_task_definitions PRIMARY KEY (id)
)
""",
    """
CREATE UNIQUE INDEX ix_task_definitions_key ON task_definitions ("key")
""",
    """
CREATE TABLE download_profiles_podcast (
    id INTEGER NOT NULL,
    download_with_countdown BOOLEAN NOT NULL,
    redownload_final BOOLEAN NOT NULL,
    download_days_in_past INTEGER NOT NULL,
    delete_older_episodes BOOLEAN NOT NULL, download_episode_count INTEGER DEFAULT '0' NOT NULL, download_starting_from DATE,
    CONSTRAINT pk_download_profiles_podcast PRIMARY KEY (id),
    CONSTRAINT fk_download_profiles_podcast_id_download_profiles FOREIGN KEY(id) REFERENCES download_profiles (id) ON DELETE CASCADE
)
""",
    """
CREATE TABLE download_profiles_series (
    id INTEGER NOT NULL,
    include_upcoming_seasons BOOLEAN NOT NULL,
    CONSTRAINT pk_download_profiles_series PRIMARY KEY (id),
    CONSTRAINT fk_download_profiles_series_id_download_profiles FOREIGN KEY(id) REFERENCES download_profiles (id) ON DELETE CASCADE
)
""",
    """
CREATE TABLE task_runs (
    id INTEGER NOT NULL,
    schedule_id INTEGER,
    definition_id INTEGER NOT NULL,
    resource_type VARCHAR(23) NOT NULL,
    resource_id INTEGER,
    status VARCHAR(15) NOT NULL,
    progress INTEGER,
    message VARCHAR,
    meta JSON,
    attempt_count INTEGER NOT NULL,
    max_retries INTEGER NOT NULL,
    last_error VARCHAR,
    next_retry_at DATETIME,
    started_at DATETIME,
    finished_at DATETIME,
    runtime_ms INTEGER,
    created_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
    updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL, result JSON,
    CONSTRAINT pk_task_runs PRIMARY KEY (id),
    CONSTRAINT fk_task_runs_definition_id_task_definitions FOREIGN KEY(definition_id) REFERENCES task_definitions (id) ON DELETE CASCADE,
    CONSTRAINT fk_task_runs_schedule_id_task_schedules FOREIGN KEY(schedule_id) REFERENCES task_schedules (id) ON DELETE SET NULL
)
""",
    """
CREATE INDEX ix_task_runs_definition_id ON task_runs (definition_id)
""",
    """
CREATE INDEX ix_task_runs_resource_id ON task_runs (resource_id)
""",
    """
CREATE INDEX ix_task_runs_resource_type ON task_runs (resource_type)
""",
    """
CREATE INDEX ix_task_runs_schedule_id ON task_runs (schedule_id)
""",
    """
CREATE INDEX ix_task_runs_status ON task_runs (status)
""",
    """
CREATE TABLE media_downloads_movie (
    id INTEGER NOT NULL,
    CONSTRAINT pk_media_downloads_movie PRIMARY KEY (id),
    CONSTRAINT fk_media_downloads_movie_id_media_downloads FOREIGN KEY(id) REFERENCES media_downloads (id) ON DELETE CASCADE
)
""",
    """
CREATE TABLE local_media_profiles_movie (
    id INTEGER NOT NULL,
    CONSTRAINT pk_local_media_profiles_movie PRIMARY KEY (id),
    CONSTRAINT fk_local_media_profiles_movie_id_local_media_profiles FOREIGN KEY(id) REFERENCES local_media_profiles (id) ON DELETE CASCADE
)
""",
    """
CREATE TABLE local_media_profiles_show (
    id INTEGER NOT NULL, show_scope VARCHAR DEFAULT 'both' NOT NULL, download_show_assets BOOLEAN,
    CONSTRAINT pk_local_media_profiles_show PRIMARY KEY (id),
    CONSTRAINT fk_local_media_profiles_show_id_local_media_profiles FOREIGN KEY(id) REFERENCES local_media_profiles (id) ON DELETE CASCADE
)
""",
    """
CREATE TABLE media_downloads_movie_extra (
    id INTEGER NOT NULL,
    CONSTRAINT pk_media_downloads_movie_extra PRIMARY KEY (id),
    CONSTRAINT fk_media_downloads_movie_extra_id_media_downloads FOREIGN KEY(id) REFERENCES media_downloads (id) ON DELETE CASCADE
)
""",
    """
CREATE TABLE "settings" (
    id INTEGER NOT NULL,
    created_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
    updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
    onboarding_completed BOOLEAN DEFAULT 0 NOT NULL, alembic_version_num VARCHAR(32), background_migration_version VARCHAR(32),
    CONSTRAINT pk_settings PRIMARY KEY (id)
)
""",
    """
CREATE TABLE "local_media_profiles" (
    id INTEGER NOT NULL,
    slug VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    output_template VARCHAR NOT NULL,
    preferred_format VARCHAR NOT NULL,
    created_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
    updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
    type VARCHAR DEFAULT 'show' NOT NULL,
    append_media_type_to_filename BOOLEAN DEFAULT 0 NOT NULL, download_mode VARCHAR(16) DEFAULT 'system' NOT NULL, thumbnail_mode VARCHAR(24) DEFAULT 'system' NOT NULL, metadata_mode VARCHAR(24) DEFAULT 'system' NOT NULL,
    CONSTRAINT pk_local_media_profiles PRIMARY KEY (id),
    CONSTRAINT uq_local_media_profiles_name UNIQUE (name)
)
""",
    """
CREATE UNIQUE INDEX ix_local_media_profiles_slug ON local_media_profiles (slug)
""",
    """
CREATE UNIQUE INDEX uq_local_media_profiles_type_output_template_preferred_format ON local_media_profiles (type, output_template, preferred_format)
""",
    """
CREATE TABLE "download_profiles" (
    id INTEGER NOT NULL,
    show_id INTEGER NOT NULL,
    local_media_profile_id INTEGER NOT NULL,
    type VARCHAR NOT NULL,
    enable_profile BOOLEAN NOT NULL,
    ep_id_type_list JSON NOT NULL,
    created_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
    updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
    CONSTRAINT pk_download_profiles PRIMARY KEY (id),
    CONSTRAINT fk_download_profiles_local_media_profile_id_local_media_profiles FOREIGN KEY(local_media_profile_id) REFERENCES local_media_profiles (id),
    CONSTRAINT fk_download_profiles_show_id_shows FOREIGN KEY(show_id) REFERENCES shows (id)
)
""",
    """
CREATE TABLE task_operations (
    id VARCHAR(36) NOT NULL,
    kind VARCHAR(120) NOT NULL,
    source VARCHAR(20) NOT NULL,
    resource_type VARCHAR(80) NOT NULL,
    resource_id INTEGER,
    title VARCHAR(255) NOT NULL,
    status VARCHAR(24) NOT NULL,
    progress INTEGER,
    message TEXT,
    result JSON,
    context JSON,
    error TEXT,
    notification_seen_at DATETIME,
    started_at DATETIME,
    finished_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, prioritized_at DATETIME, completion_progress INTEGER DEFAULT 0,
    CONSTRAINT pk_task_operations PRIMARY KEY (id)
)
""",
    """
CREATE INDEX ix_task_operations_kind ON task_operations (kind)
""",
    """
CREATE INDEX ix_task_operations_source ON task_operations (source)
""",
    """
CREATE INDEX ix_task_operations_resource_type ON task_operations (resource_type)
""",
    """
CREATE INDEX ix_task_operations_resource_id ON task_operations (resource_id)
""",
    """
CREATE INDEX ix_task_operations_status ON task_operations (status)
""",
    """
CREATE INDEX ix_task_operations_notification_seen_at ON task_operations (notification_seen_at)
""",
    """
CREATE TABLE task_operation_targets (
    id INTEGER NOT NULL,
    operation_id VARCHAR(36) NOT NULL,
    task_key VARCHAR(120) NOT NULL,
    resource_type VARCHAR(80) NOT NULL,
    resource_id INTEGER,
    slot_key VARCHAR(255) NOT NULL,
    task_kwargs JSON,
    recover_on_restart BOOLEAN DEFAULT 1 NOT NULL,
    CONSTRAINT pk_task_operation_targets PRIMARY KEY (id),
    CONSTRAINT fk_task_operation_targets_operation_id_task_operations FOREIGN KEY(operation_id) REFERENCES task_operations (id) ON DELETE CASCADE,
    CONSTRAINT uq_task_operation_targets_operation_slot UNIQUE (operation_id, slot_key)
)
""",
    """
CREATE INDEX ix_task_operation_targets_operation_id ON task_operation_targets (operation_id)
""",
    """
CREATE INDEX ix_task_operation_targets_task_key ON task_operation_targets (task_key)
""",
    """
CREATE INDEX ix_task_operation_targets_resource_type ON task_operation_targets (resource_type)
""",
    """
CREATE INDEX ix_task_operation_targets_resource_id ON task_operation_targets (resource_id)
""",
    """
CREATE TABLE task_operation_runs (
    target_id INTEGER NOT NULL,
    task_run_id INTEGER NOT NULL,
    operation_id VARCHAR(36) NOT NULL,
    CONSTRAINT pk_task_operation_runs PRIMARY KEY (target_id, task_run_id),
    CONSTRAINT fk_task_operation_runs_operation_id_task_operations FOREIGN KEY(operation_id) REFERENCES task_operations (id) ON DELETE CASCADE,
    CONSTRAINT fk_task_operation_runs_target_id_task_operation_targets FOREIGN KEY(target_id) REFERENCES task_operation_targets (id) ON DELETE CASCADE,
    CONSTRAINT fk_task_operation_runs_task_run_id_task_runs FOREIGN KEY(task_run_id) REFERENCES task_runs (id) ON DELETE CASCADE
)
""",
    """
CREATE INDEX ix_task_operation_runs_task_run_id ON task_operation_runs (task_run_id)
""",
    """
CREATE INDEX ix_task_operation_runs_operation_id ON task_operation_runs (operation_id)
""",
    """
CREATE TABLE "media_downloads_episode" (
    id INTEGER NOT NULL,
    download_profile_id INTEGER,
    downloaded_publish_status VARCHAR, redownload_when_final BOOLEAN DEFAULT 0 NOT NULL, redownload_when_delay_passed BOOLEAN DEFAULT 0 NOT NULL,
    CONSTRAINT pk_media_downloads_episode PRIMARY KEY (id),
    CONSTRAINT fk_media_downloads_episode_id_media_downloads FOREIGN KEY(id) REFERENCES media_downloads (id) ON DELETE CASCADE,
    CONSTRAINT fk_media_downloads_episode_download_profile_id_download_profiles FOREIGN KEY(download_profile_id) REFERENCES download_profiles (id)
)
""",
    """
CREATE TABLE "task_schedules" (
    id INTEGER NOT NULL,
    definition_id INTEGER NOT NULL,
    scheduler_job_id VARCHAR,
    resource_id INTEGER NOT NULL,
    resource_type VARCHAR(23) NOT NULL,
    "trigger" VARCHAR(20) NOT NULL,
    trigger_args JSON NOT NULL,
    next_run_time DATETIME,
    active BOOLEAN NOT NULL,
    max_retries INTEGER,
    created_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
    updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
    CONSTRAINT pk_task_schedules PRIMARY KEY (id),
    CONSTRAINT fk_task_schedules_definition_id_task_definitions FOREIGN KEY(definition_id) REFERENCES task_definitions (id) ON DELETE CASCADE
)
""",
    """
CREATE INDEX ix_task_schedules_definition_id ON task_schedules (definition_id)
""",
    """
CREATE INDEX ix_task_schedules_scheduler_job_id ON task_schedules (scheduler_job_id)
""",
    """
CREATE INDEX ix_task_schedules_active ON task_schedules (active)
""",
    """
CREATE INDEX ix_task_schedules_resource_type ON task_schedules (resource_type)
""",
    """
CREATE INDEX ix_task_schedules_resource_id ON task_schedules (resource_id)
""",
    """
CREATE TABLE "media_items_episode" (
    id INTEGER NOT NULL,
    show_id INTEGER NOT NULL,
    season_id INTEGER NOT NULL,
    "index" INTEGER NOT NULL,
    episode_identifier VARCHAR NOT NULL,
    slug VARCHAR NOT NULL,
    publish_status VARCHAR NOT NULL,
    video_url VARCHAR,
    audio_url VARCHAR,
    sharing_url VARCHAR NOT NULL,
    went_live_date DATETIME,
    published_date DATETIME,
    scheduled_date DATETIME,
    metadata_is_final BOOLEAN DEFAULT 1 NOT NULL, title VARCHAR DEFAULT '' NOT NULL, description VARCHAR, duration FLOAT DEFAULT '0' NOT NULL, background_image_path VARCHAR, thumbnail_landscape_path VARCHAR, thumbnail_portrait_path VARCHAR, thumbnail_square_path VARCHAR, dw_episode_number VARCHAR,
    CONSTRAINT pk_episodes PRIMARY KEY (id, show_id),
    CONSTRAINT fk_episodes_show_id_shows FOREIGN KEY(show_id) REFERENCES shows (id),
    CONSTRAINT fk_episodes_season_id_seasons FOREIGN KEY(season_id) REFERENCES seasons (id),
    CONSTRAINT fk_episodes_id_media_items FOREIGN KEY(id) REFERENCES media_items (id) ON DELETE CASCADE,
    CONSTRAINT uq_unique_episode_identifier_per_show UNIQUE (show_id, episode_identifier),
    CONSTRAINT uq_episode_show_index UNIQUE (show_id, "index")
)
""",
    """
CREATE UNIQUE INDEX ix_episodes_slug ON "media_items_episode" (slug)
""",
    """
CREATE TABLE "media_items_movie" (
    id INTEGER NOT NULL,
    slug VARCHAR NOT NULL,
    extended_title VARCHAR,
    sharing_url VARCHAR,
    author_name VARCHAR,
    author_slug VARCHAR,
    logo_image_path VARCHAR,
    mature_rating VARCHAR,
    is_downloadable BOOLEAN,
    available_for JSON DEFAULT '[]' NOT NULL,
    release_date DATE,
    release_date_source VARCHAR,
    release_date_source_id VARCHAR,
    release_date_lookup_status VARCHAR DEFAULT 'pending' NOT NULL,
    release_date_lookup_attempted_at DATETIME,
    release_date_lookup_error VARCHAR,
    official_trailer_id INTEGER,
    has_video BOOLEAN DEFAULT 0 NOT NULL,
    status VARCHAR,
    published_at DATETIME,
    background VARCHAR,
    byline VARCHAR,
    language VARCHAR,
    origin_country VARCHAR,
    images JSON DEFAULT '{}' NOT NULL,
    cast_and_crew JSON DEFAULT '[]' NOT NULL,
    directed_by JSON DEFAULT '[]' NOT NULL,
    genres JSON DEFAULT '[]' NOT NULL,
    hosts JSON DEFAULT '[]' NOT NULL,
    production_companies JSON DEFAULT '[]' NOT NULL,
    starring JSON DEFAULT '[]' NOT NULL,
    written_by JSON DEFAULT '[]' NOT NULL, title VARCHAR DEFAULT '' NOT NULL, description VARCHAR, duration FLOAT DEFAULT '0' NOT NULL, background_image_path VARCHAR, thumbnail_landscape_path VARCHAR, thumbnail_portrait_path VARCHAR, thumbnail_square_path VARCHAR,
    CONSTRAINT pk_movies PRIMARY KEY (id),
    CONSTRAINT fk_movies_id_media_items FOREIGN KEY(id) REFERENCES media_items (id) ON DELETE CASCADE,
    CONSTRAINT uq_movies_official_trailer_id UNIQUE (official_trailer_id),
    CONSTRAINT fk_movies_official_trailer_id_movie_extras FOREIGN KEY(official_trailer_id) REFERENCES "media_items_movie_extra" (id) ON DELETE SET NULL
)
""",
    """
CREATE UNIQUE INDEX ix_movies_slug ON "media_items_movie" (slug)
""",
    """
CREATE TABLE movie_extra_sources (
    id INTEGER NOT NULL,
    slug VARCHAR NOT NULL, title VARCHAR DEFAULT '' NOT NULL, description VARCHAR, duration FLOAT DEFAULT '0' NOT NULL, background_image_path VARCHAR, thumbnail_landscape_path VARCHAR, thumbnail_portrait_path VARCHAR, thumbnail_square_path VARCHAR, sharing_url VARCHAR, published_date DATETIME, available_for JSON DEFAULT '[]' NOT NULL,
    CONSTRAINT pk_movie_extra_sources PRIMARY KEY (id),
    CONSTRAINT uq_movie_extra_sources_slug UNIQUE (slug)
)
""",
    """
CREATE TABLE "media_items_movie_extra" (
    id INTEGER NOT NULL,
    movie_id INTEGER NOT NULL,
    movie_extra_type VARCHAR DEFAULT 'other' NOT NULL,
    source_id INTEGER NOT NULL,
    CONSTRAINT pk_movie_extras PRIMARY KEY (id),
    CONSTRAINT fk_movie_extras_source_id_movie_extra_sources FOREIGN KEY(source_id) REFERENCES movie_extra_sources (id) ON DELETE RESTRICT,
    CONSTRAINT fk_movie_extras_id_media_items FOREIGN KEY(id) REFERENCES media_items (id) ON DELETE CASCADE,
    CONSTRAINT uq_movie_extras_movie_id_source_id UNIQUE (movie_id, source_id),
    CONSTRAINT fk_movie_extras_movie_id_movies FOREIGN KEY(movie_id) REFERENCES "media_items_movie" (id) ON DELETE CASCADE
)
""",
    """
CREATE INDEX ix_movie_extras_source_id ON "media_items_movie_extra" (source_id)
""",
    """
CREATE INDEX ix_movie_extras_movie_id ON "media_items_movie_extra" (movie_id)
""",
    """
CREATE TABLE "download_profile_series_seasons" (
    download_profiles_series_id INTEGER,
    season_id INTEGER,
    CONSTRAINT fk_download_profile_series_seasons_series_download_profile_id_download_profiles_series FOREIGN KEY(download_profiles_series_id) REFERENCES download_profiles_series (id),
    CONSTRAINT fk_download_profile_series_seasons_season_id_seasons FOREIGN KEY(season_id) REFERENCES seasons (id)
)
""",
    """
CREATE TABLE "seasons" (
    id INTEGER NOT NULL,
    show_id INTEGER NOT NULL,
    "index" INTEGER NOT NULL,
    slug VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    created_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
    updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL, season_type VARCHAR DEFAULT 'normal' NOT NULL, season_number INTEGER DEFAULT '1' NOT NULL,
    CONSTRAINT pk_seasons PRIMARY KEY (id),
    CONSTRAINT uq_season_show_index UNIQUE (show_id, "index"),
    CONSTRAINT fk_seasons_show_id_shows FOREIGN KEY(show_id) REFERENCES shows (id),
    CONSTRAINT uq_season_show_slug UNIQUE (show_id, slug)
)
""",
    """
CREATE INDEX ix_seasons_slug ON seasons (slug)
""",
    """
CREATE INDEX ix_task_operations_prioritized_at ON task_operations (prioritized_at)
""",
    """
CREATE TABLE "stream_profiles_rss" (
    id INTEGER NOT NULL,
    feed_url VARCHAR NOT NULL,
    video_output_mode VARCHAR,
    max_items INTEGER DEFAULT '0' NOT NULL,
    stream_live_episodes BOOLEAN DEFAULT 0 NOT NULL,
    live_episode_handoff_ids JSON DEFAULT '[]' NOT NULL,
    CONSTRAINT pk_stream_profiles_rss PRIMARY KEY (id),
    CONSTRAINT fk_stream_profiles_rss_id_stream_profiles FOREIGN KEY(id) REFERENCES stream_profiles (id) ON DELETE CASCADE
)
""",
    """
CREATE TABLE "stream_profiles" (
    id INTEGER NOT NULL,
    type VARCHAR NOT NULL,
    show_id INTEGER NOT NULL,
    enable_profile BOOLEAN NOT NULL,
    token VARCHAR NOT NULL,
    use_downloads BOOLEAN NOT NULL,
    use_dw_stream BOOLEAN NOT NULL,
    preferred_format VARCHAR NOT NULL,
    prefer_exact_match BOOLEAN NOT NULL,
    created_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
    updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
    ep_id_type_list JSON DEFAULT '["ep", "aux"]' NOT NULL, overwrite_show_title VARCHAR,
    CONSTRAINT pk_stream_profiles PRIMARY KEY (id),
    CONSTRAINT fk_stream_profiles_show_id_shows FOREIGN KEY(show_id) REFERENCES shows (id)
)
""",
    """
CREATE UNIQUE INDEX ix_stream_profiles_token ON stream_profiles (token)
""",
    """
CREATE TABLE custom_index_states (
    id INTEGER NOT NULL,
    show_id INTEGER NOT NULL,
    local_media_profile_id INTEGER NOT NULL,
    requested_generation INTEGER DEFAULT '1' NOT NULL,
    completed_generation INTEGER DEFAULT '0' NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pk_custom_index_states PRIMARY KEY (id),
    CONSTRAINT uq_custom_index_state_scope UNIQUE (show_id, local_media_profile_id),
    CONSTRAINT fk_custom_index_states_show_id_shows FOREIGN KEY(show_id) REFERENCES shows (id) ON DELETE CASCADE,
    CONSTRAINT fk_custom_index_states_local_media_profile_id_local_media_profiles FOREIGN KEY(local_media_profile_id) REFERENCES local_media_profiles (id) ON DELETE CASCADE
)
""",
    """
CREATE INDEX ix_custom_index_states_show_id ON custom_index_states (show_id)
""",
    """
CREATE INDEX ix_custom_index_states_local_media_profile_id ON custom_index_states (local_media_profile_id)
""",
    """
CREATE TABLE media_download_history (
    id INTEGER NOT NULL,
    media_download_id INTEGER NOT NULL,
    action VARCHAR(32) NOT NULL,
    metadata JSON NOT NULL,
    occurred_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pk_media_download_history PRIMARY KEY (id),
    CONSTRAINT fk_media_download_history_media_download_id_media_downloads FOREIGN KEY(media_download_id) REFERENCES media_downloads (id) ON DELETE CASCADE
)
""",
    """
CREATE INDEX ix_media_download_history_media_download_id ON media_download_history (media_download_id)
""",
    """
CREATE INDEX ix_media_download_history_action ON media_download_history (action)
""",
    """
CREATE INDEX ix_media_download_history_occurred_at ON media_download_history (occurred_at)
""",
    """
CREATE TABLE show_local_assets (
    id INTEGER NOT NULL,
    show_id INTEGER NOT NULL,
    local_media_profile_id INTEGER NOT NULL,
    asset_type VARCHAR(16) NOT NULL,
    file_path VARCHAR NOT NULL,
    source_url VARCHAR,
    source_format VARCHAR(16),
    content_hash VARCHAR(64),
    pending_hash VARCHAR(64),
    checked_at DATETIME,
    CONSTRAINT pk_show_local_assets PRIMARY KEY (id),
    CONSTRAINT uq_show_local_asset_target UNIQUE (show_id, local_media_profile_id, asset_type, file_path),
    CONSTRAINT fk_show_local_assets_show_id_shows FOREIGN KEY(show_id) REFERENCES shows (id) ON DELETE CASCADE,
    CONSTRAINT fk_show_local_assets_local_media_profile_id_local_media_profiles FOREIGN KEY(local_media_profile_id) REFERENCES local_media_profiles (id) ON DELETE CASCADE
)
""",
    """
CREATE INDEX ix_show_local_assets_show_id ON show_local_assets (show_id)
""",
    """
CREATE INDEX ix_show_local_assets_local_media_profile_id ON show_local_assets (local_media_profile_id)
""",
    """
CREATE TABLE task_operation_dependencies (
    id INTEGER NOT NULL,
    parent_operation_id VARCHAR(36) NOT NULL,
    child_operation_id VARCHAR(36),
    slot_key VARCHAR(255) NOT NULL,
    weight FLOAT DEFAULT 1 NOT NULL,
    required BOOLEAN DEFAULT 1 NOT NULL,
    cancel_policy VARCHAR(32) DEFAULT 'detach' NOT NULL,
    context JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pk_task_operation_dependencies PRIMARY KEY (id),
    CONSTRAINT uq_task_operation_dependencies_parent_slot UNIQUE (parent_operation_id, slot_key),
    CONSTRAINT uq_task_operation_dependencies_parent_child UNIQUE (parent_operation_id, child_operation_id),
    CONSTRAINT fk_task_operation_dependencies_parent_operation_id_task_operations FOREIGN KEY(parent_operation_id) REFERENCES task_operations (id) ON DELETE CASCADE,
    CONSTRAINT fk_task_operation_dependencies_child_operation_id_task_operations FOREIGN KEY(child_operation_id) REFERENCES task_operations (id) ON DELETE SET NULL
)
""",
    """
CREATE INDEX ix_task_operation_dependencies_parent_operation_id ON task_operation_dependencies (parent_operation_id)
""",
    """
CREATE INDEX ix_task_operation_dependencies_child_operation_id ON task_operation_dependencies (child_operation_id)
""",
    """
CREATE TABLE media_download_assets (
    id INTEGER NOT NULL,
    media_download_id INTEGER NOT NULL,
    asset_key VARCHAR(120) NOT NULL,
    kind VARCHAR(40) NOT NULL,
    path VARCHAR NOT NULL,
    suffix VARCHAR(120) NOT NULL,
    size_bytes BIGINT,
    fingerprint VARCHAR(64),
    CONSTRAINT pk_media_download_assets PRIMARY KEY (id),
    CONSTRAINT uq_download_asset_key UNIQUE (media_download_id, asset_key),
    CONSTRAINT fk_media_download_assets_media_download_id_media_downloads FOREIGN KEY(media_download_id) REFERENCES media_downloads (id) ON DELETE CASCADE
)
""",
    """
CREATE INDEX ix_media_download_assets_media_download_id ON media_download_assets (media_download_id)
""",
    """
CREATE TABLE "media_downloads" (
    id INTEGER NOT NULL,
    type VARCHAR NOT NULL,
    media_item_id INTEGER NOT NULL,
    local_media_profile_id INTEGER NOT NULL,
    file_path VARCHAR NOT NULL,
    downloaded_bytes INTEGER,
    format_downloaded VARCHAR,
    created_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
    updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
    artifact_status VARCHAR(24) DEFAULT 'absent' NOT NULL,
    artifact_error TEXT,
    automatic_retry_suppressed BOOLEAN DEFAULT 0 NOT NULL,
    downloaded_at DATETIME,
    artifact_stat_dev VARCHAR(32),
    artifact_stat_ino VARCHAR(32),
    artifact_size_bytes BIGINT,
    artifact_fingerprint VARCHAR(64),
    CONSTRAINT pk_media_downloads PRIMARY KEY (id),
    CONSTRAINT fk_media_downloads_media_item_id_media_items FOREIGN KEY(media_item_id) REFERENCES media_items (id),
    CONSTRAINT fk_media_downloads_local_media_profile_id_local_media_profiles FOREIGN KEY(local_media_profile_id) REFERENCES local_media_profiles (id),
    CONSTRAINT uq_download_per_media_profile UNIQUE (media_item_id, local_media_profile_id),
    CONSTRAINT ck_media_downloads_ck_media_downloads_artifact_identity_complete CHECK (artifact_status IN ('absent', 'missing') OR (artifact_stat_dev IS NOT NULL AND length(artifact_stat_dev) > 0 AND artifact_stat_ino IS NOT NULL AND length(artifact_stat_ino) > 0 AND artifact_size_bytes IS NOT NULL AND artifact_size_bytes >= 0 AND artifact_fingerprint IS NOT NULL AND length(artifact_fingerprint) = 64))
)
""",
    """
CREATE INDEX ix_media_downloads_artifact_status ON media_downloads (artifact_status)
""",
    """
CREATE INDEX ix_media_items_episode_show_published_id ON media_items_episode (show_id, published_date, id)
""",
    """
CREATE INDEX ix_task_runs_definition_status_resource_started_id ON task_runs (definition_id, status, resource_type, resource_id, started_at, id)
""",
    """
CREATE INDEX ix_media_items_episode_show_publish_status ON media_items_episode (show_id, publish_status)
""",
    """
CREATE INDEX ix_media_items_episode_season_index_id ON media_items_episode (season_id, "index", id)
""",
    """
CREATE INDEX ix_media_items_episode_unfinished_metadata_status ON media_items_episode (publish_status) WHERE metadata_is_final = 0
""",
    """
CREATE INDEX ix_media_download_history_download_occurred_id ON media_download_history (media_download_id, occurred_at, id)
""",
    """
CREATE INDEX ix_media_downloads_local_profile_id ON media_downloads (local_media_profile_id, id)
""",
)

_TABLES = (
    "metadata",
    "shows",
    "media_items",
    "task_definitions",
    "download_profiles_podcast",
    "download_profiles_series",
    "task_runs",
    "media_downloads_movie",
    "local_media_profiles_movie",
    "local_media_profiles_show",
    "media_downloads_movie_extra",
    "settings",
    "local_media_profiles",
    "download_profiles",
    "task_operations",
    "task_operation_targets",
    "task_operation_runs",
    "media_downloads_episode",
    "task_schedules",
    "media_items_episode",
    "media_items_movie",
    "movie_extra_sources",
    "media_items_movie_extra",
    "download_profile_series_seasons",
    "seasons",
    "stream_profiles_rss",
    "stream_profiles",
    "custom_index_states",
    "media_download_history",
    "show_local_assets",
    "task_operation_dependencies",
    "media_download_assets",
    "media_downloads",
)



def upgrade() -> None:
    for statement in _SCHEMA:
        op.execute(statement)


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.execute(f'DROP TABLE "{table}"')
