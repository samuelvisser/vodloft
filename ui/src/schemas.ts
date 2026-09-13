import {z} from 'zod'

export const Video = z.object({
  id: z.number(), source_url: z.string(), extractor: z.string(), extractor_id: z.string(),
  title: z.string(), description: z.string().nullable(), uploader: z.string().nullable(),
  channel: z.string().nullable(), duration: z.number().nullable(), upload_date: z.string().nullable(),
  thumbnail_url: z.string().nullable(), standalone: z.boolean(), downloaded_path: z.string().nullable(),
  downloaded_format: z.string().nullable(), downloaded_at: z.string().nullable(),
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

export const DownloadProfile = z.object({
  id: z.number(), name: z.string(), local_media_profile_id: z.number(), format_selector: z.string(),
  merge_output_format: z.string().nullable(), audio_format: z.string().nullable(),
  write_subtitles: z.boolean(), embed_metadata: z.boolean(), embed_thumbnail: z.boolean(),
})
export type DownloadProfile = z.infer<typeof DownloadProfile>

export const Task = z.object({
  id: z.string(), name: z.string(), status: z.string(), progress: z.number(), message: z.string().nullable(),
  created_at: z.string(), started_at: z.string().nullable(), finished_at: z.string().nullable(),
  error: z.string().nullable(), result: z.unknown().optional(),
})
export type Task = z.infer<typeof Task>
