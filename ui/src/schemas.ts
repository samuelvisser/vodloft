import {z} from 'zod'

export const MediaDownload = z.object({
  id: z.number(), video_id: z.number(), local_media_profile_id: z.number(), status: z.string(),
  file_path: z.string().nullable(), downloaded_bytes: z.number().nullable(),
  format_downloaded: z.string().nullable(), error: z.string().nullable(),
  downloaded_at: z.string().nullable(), created_at: z.string(), updated_at: z.string(),
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

export const StreamTarget = z.object({
  url: z.string(), format_id: z.string().nullable().optional(), ext: z.string().nullable().optional(),
  protocol: z.string().nullable().optional(), vcodec: z.string().nullable().optional(),
  acodec: z.string().nullable().optional(), http_headers: z.record(z.string(), z.string()).optional(),
})
export type StreamTarget = z.infer<typeof StreamTarget>

export const Task = z.object({
  id: z.string(), name: z.string(), status: z.string(), progress: z.number(), message: z.string().nullable(),
  created_at: z.string(), started_at: z.string().nullable(), finished_at: z.string().nullable(),
  error: z.string().nullable(), result: z.unknown().optional(),
})
export type Task = z.infer<typeof Task>
