import {z} from 'zod'

export const MediaDownload = z.object({
  id: z.number(), video_id: z.number(), local_media_profile_id: z.number(), status: z.string(),
  file_path: z.string().nullable(), downloaded_bytes: z.number().nullable(),
  format_downloaded: z.string().nullable(), error: z.string().nullable(),
  downloaded_at: z.string().nullable(), task_run_id: z.number().nullable(), created_at: z.string(), updated_at: z.string(),
})
export type MediaDownload = z.infer<typeof MediaDownload>

export const Video = z.object({
  id: z.number(), source_url: z.string(), extractor: z.string(), extractor_id: z.string(),
  title: z.string(), description: z.string().nullable(), uploader: z.string().nullable(),
  channel: z.string().nullable(), duration: z.number().nullable(), upload_date: z.string().nullable(),
  thumbnail_url: z.string().nullable(), standalone: z.boolean(), media_downloads: z.array(MediaDownload),
})
export type Video = z.infer<typeof Video>

export const Collection = z.object({
  id: z.number(), kind: z.enum(['channel', 'playlist']), source_url: z.string(),
  extractor: z.string(), extractor_id: z.string(), title: z.string(),
  description: z.string().nullable(), uploader: z.string().nullable(), channel: z.string().nullable(),
  thumbnail_url: z.string().nullable(), last_synced_at: z.string().nullable(), videos: z.array(Video),
})
export type Collection = z.infer<typeof Collection>

export const SourceInspection = z.object({
  kind: z.string(), title: z.string(), extractor: z.string(), extractor_id: z.string(),
  url: z.string(), entry_count: z.number().nullable().optional(),
})

export const LocalMediaProfile = z.object({
  id: z.number(), slug: z.string().nullable(), name: z.string(), scope: z.enum(['collection', 'video']),
  media_kind: z.enum(['video', 'audio']), output_template: z.string(), preferred_format: z.string(),
  merge_output_format: z.string().nullable(), audio_format: z.string().nullable(),
  write_subtitles: z.boolean(), embed_metadata: z.boolean(), embed_thumbnail: z.boolean(),
})
export type LocalMediaProfile = z.infer<typeof LocalMediaProfile>

export const DownloadProfile = z.object({
  id: z.number(), name: z.string(), collection_id: z.number(), local_media_profile_id: z.number(),
  enable_profile: z.boolean(),
})
export type DownloadProfile = z.infer<typeof DownloadProfile>

export const StreamProfile = z.object({
  id: z.number(), name: z.string(), collection_id: z.number(), enable_profile: z.boolean(),
  use_downloads: z.boolean(), format_selector: z.string(),
})
export type StreamProfile = z.infer<typeof StreamProfile>

export const OutputTemplatePreview = z.object({
  valid: z.boolean(), normalized_template: z.string().nullable().optional(), example_output: z.string().nullable().optional(), error: z.string().nullable().optional(),
})
export type OutputTemplatePreview = z.infer<typeof OutputTemplatePreview>

export const StreamTarget = z.object({
  url: z.string(), format_id: z.string().nullable().optional(), ext: z.string().nullable().optional(),
  protocol: z.string().nullable().optional(), vcodec: z.string().nullable().optional(),
  acodec: z.string().nullable().optional(), http_headers: z.record(z.string(), z.string()).optional(),
})
export type StreamTarget = z.infer<typeof StreamTarget>

export const TaskRun = z.object({
  id: z.number(), task_key: z.string(), task_title: z.string(), schedule_id: z.number().nullable(),
  operation_id: z.number().nullable(), resource_type: z.string(), resource_id: z.number(), source: z.string(),
  status: z.string(), progress: z.number(), message: z.string().nullable(), payload: z.record(z.string(), z.unknown()),
  result: z.unknown().optional(), attempt_count: z.number(), max_retries: z.number(), last_error: z.string().nullable(),
  next_retry_at: z.string().nullable(), cancellation_requested: z.boolean(), priority_at: z.string().nullable(), queued_at: z.string(),
  started_at: z.string().nullable(), finished_at: z.string().nullable(), progress_updated_at: z.string().nullable(),
  runtime_seconds: z.number().nullable(), created_at: z.string(), updated_at: z.string(),
})
export type TaskRun = z.infer<typeof TaskRun>
// Compatibility name for components that only care about a submitted run.
export const Task = TaskRun
export type Task = TaskRun

export const TaskLedger = z.object({
  items: z.array(TaskRun), page: z.number(), page_size: z.number(), total: z.number(), pages: z.number(),
})
export type TaskLedger = z.infer<typeof TaskLedger>

export const TaskDefinition = z.object({
  id: z.number(), key: z.string(), title: z.string(), description: z.string(),
  allowed_resource_types: z.array(z.string()), default_max_retries: z.number().nullable(), tracks_progress: z.boolean(),
})
export type TaskDefinition = z.infer<typeof TaskDefinition>

export const TaskSchedule = z.object({
  id: z.number(), task_key: z.string(), task_title: z.string(), name: z.string(), source: z.string(),
  registry_key: z.string().nullable(), resource_type: z.string(), resource_id: z.number(), trigger_type: z.string(),
  trigger_args: z.record(z.string(), z.unknown()), payload: z.record(z.string(), z.unknown()), active: z.boolean(),
  coalesce: z.boolean(), max_retries: z.number().nullable(), next_run_time: z.string().nullable(),
  last_error: z.string().nullable(), created_at: z.string(), updated_at: z.string(),
})
export type TaskSchedule = z.infer<typeof TaskSchedule>

export const TaskOperation = z.object({
  id: z.number(), title: z.string(), source: z.string(), status: z.string(), total_tasks: z.number(),
  completed_tasks: z.number(), succeeded_tasks: z.number(), failed_tasks: z.number(), canceled_tasks: z.number(),
  meta: z.record(z.string(), z.unknown()), started_at: z.string().nullable(), finished_at: z.string().nullable(),
  created_at: z.string(), updated_at: z.string(),
})
export type TaskOperation = z.infer<typeof TaskOperation>

export const AuthStatus = z.object({
  auth_enabled: z.boolean(), setup_required: z.boolean(), authenticated: z.boolean(), username: z.string(),
  onboarding_completed: z.boolean(),
})
export type AuthStatus = z.infer<typeof AuthStatus>

export const ApplicationSettings = z.object({
  onboarding_completed: z.boolean(), alembic_version_num: z.string().nullable(), auth_enabled: z.boolean(),
  admin_username: z.string(), rss_token: z.string(), rss_item_limit: z.number(), worker_threads: z.number(),
  scheduler_enabled: z.boolean(), collection_sync_interval_minutes: z.number(), verification_interval_minutes: z.number(),
  default_max_retries: z.number(), retry_backoff_base_seconds: z.number(), retry_backoff_max_seconds: z.number(),
  stalled_timeout_minutes: z.number(), download_max_concurrency: z.number(), yt_dlp_options: z.record(z.string(), z.unknown()),
})
export type ApplicationSettings = z.infer<typeof ApplicationSettings>
