import {z} from 'zod'
import {
  ApplicationSettings, AuthStatus, Collection, DownloadProfile, LocalMediaProfile, OutputTemplatePreview,
  MediaDownload, SourceInspection, StreamProfile, StreamTarget, TaskDefinition, TaskLedger, TaskOperation, TaskRun, TaskSchedule, Video,
} from './schemas'

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, schema: z.ZodType<T>, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: 'include',
    headers: {'Content-Type': 'application/json', ...(init?.headers ?? {})},
    ...init,
  })
  if (!response.ok) {
    const detail = (await response.json().catch(() => null))?.detail ?? response.statusText
    throw new ApiError(response.status, typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return schema.parse(await response.json())
}

async function requestVoid(path: string, init?: RequestInit): Promise<void> {
  const response = await fetch(path, {credentials: 'include', ...init})
  if (!response.ok) {
    const detail = (await response.json().catch(() => null))?.detail ?? response.statusText
    throw new ApiError(response.status, typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
}

export type LocalMediaProfileInput = {
  name: string
  scope: 'collection' | 'video'
  media_kind: 'video' | 'audio'
  output_template: string
  preferred_format: string
  merge_output_format?: string | null
  audio_format?: string | null
  write_subtitles?: boolean
  embed_metadata?: boolean
  embed_thumbnail?: boolean
}
export type DownloadProfileInput = {name: string; collection_id: number; local_media_profile_id: number; enable_profile: boolean}
export type StreamProfileInput = {name: string; collection_id: number; enable_profile: boolean; use_downloads: boolean; format_selector: string}
export type TaskScheduleInput = {
  task_key: string
  name: string
  resource_type: string
  resource_id: number
  trigger_type: 'cron' | 'interval'
  cron?: string | null
  interval_minutes?: number | null
  payload?: Record<string, unknown>
  active?: boolean
  coalesce?: boolean
  max_retries?: number | null
}

export const api = {
  authStatus: () => request('/api/auth/status', AuthStatus),
  authSetup: (username: string, password: string) => request('/api/auth/setup', AuthStatus, {method: 'POST', body: JSON.stringify({username, password})}),
  login: (username: string, password: string) => request('/api/auth/login', AuthStatus, {method: 'POST', body: JSON.stringify({username, password})}),
  logout: () => requestVoid('/api/auth/logout', {method: 'POST'}),
  changePassword: (currentPassword: string | null, newPassword: string) => requestVoid('/api/auth/password', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({current_password: currentPassword, new_password: newPassword})}),

  settings: () => request('/api/settings', ApplicationSettings),
  updateSettings: (payload: Partial<Pick<z.infer<typeof ApplicationSettings>, 'onboarding_completed' | 'auth_enabled' | 'admin_username' | 'rss_item_limit'>>) => request('/api/settings', ApplicationSettings, {method: 'PUT', body: JSON.stringify(payload)}),
  updateRuntimeSettings: (payload: Partial<Pick<z.infer<typeof ApplicationSettings>, 'worker_threads' | 'scheduler_enabled' | 'collection_sync_interval_minutes' | 'verification_interval_minutes' | 'default_max_retries' | 'retry_backoff_base_seconds' | 'retry_backoff_max_seconds' | 'stalled_timeout_minutes' | 'download_max_concurrency' | 'yt_dlp_options'>>) => request('/api/settings/runtime', ApplicationSettings, {method: 'PUT', body: JSON.stringify(payload)}),
  rotateRssToken: () => request('/api/settings/rss-token/rotate', ApplicationSettings, {method: 'POST'}),

  collections: () => request('/api/library/collections', z.array(Collection)),
  videos: () => request('/api/library/videos?standalone_only=true', z.array(Video)),
  allVideos: () => request('/api/library/videos', z.array(Video)),
  mediaDownloads: () => request('/api/media-downloads', z.array(MediaDownload)),
  retryMediaDownload: (id: number) => request(`/api/media-downloads/${id}/retry`, z.object({status: z.string(), task_run_id: z.number()}), {method: 'POST'}),
  cancelMediaDownload: (id: number) => request(`/api/media-downloads/${id}/cancel`, z.object({status: z.string(), task_run_id: z.number().nullable()}), {method: 'POST'}),
  prioritizeMediaDownload: (id: number) => request(`/api/media-downloads/${id}/prioritize`, z.object({status: z.string(), task_run_id: z.number()}), {method: 'POST'}),
  deleteMediaDownload: (id: number) => requestVoid(`/api/media-downloads/${id}`, {method: 'DELETE'}),
  inspect: (url: string) => request('/api/library/inspect', SourceInspection, {method: 'POST', body: JSON.stringify({url})}),
  addVideo: (url: string) => request('/api/library/videos', Video, {method: 'POST', body: JSON.stringify({url})}),
  addCollection: (url: string, kind?: 'channel' | 'playlist') => request('/api/library/collections', Collection, {method: 'POST', body: JSON.stringify({url, kind})}),
  deleteCollection: (id: number) => requestVoid(`/api/library/collections/${id}`, {method: 'DELETE'}),
  deleteVideo: (id: number) => requestVoid(`/api/library/videos/${id}`, {method: 'DELETE'}),
  syncCollection: (id: number) => request(`/api/library/collections/${id}/sync`, TaskRun, {method: 'POST'}),
  downloadVideo: (id: number, localMediaProfileId: number) => request(`/api/library/videos/${id}/download`, TaskRun, {method: 'POST', body: JSON.stringify({local_media_profile_id: localMediaProfileId})}),
  resolveStream: (videoId: number, profileId: number) => request(`/api/library/videos/${videoId}/stream?profile_id=${profileId}`, StreamTarget),

  localProfiles: (scope?: 'collection' | 'video') => request(`/api/profiles/local-media${scope ? `?scope=${scope}` : ''}`, z.array(LocalMediaProfile)),
  createLocalProfile: (payload: LocalMediaProfileInput) => request('/api/profiles/local-media', LocalMediaProfile, {method: 'POST', body: JSON.stringify(payload)}),
  updateLocalProfile: (id: number, payload: Partial<LocalMediaProfileInput>) => request(`/api/profiles/local-media/${id}`, LocalMediaProfile, {method: 'PUT', body: JSON.stringify(payload)}),
  deleteLocalProfile: (id: number) => requestVoid(`/api/profiles/local-media/${id}`, {method: 'DELETE'}),
  previewOutputTemplate: (template: string) => request('/api/profiles/local-media/template-preview', OutputTemplatePreview, {method: 'POST', body: JSON.stringify({output_template: template})}),

  downloadProfiles: (collectionId?: number) => request(`/api/profiles/downloads${collectionId ? `?collection_id=${collectionId}` : ''}`, z.array(DownloadProfile)),
  createDownloadProfile: (payload: DownloadProfileInput) => request('/api/profiles/downloads', DownloadProfile, {method: 'POST', body: JSON.stringify(payload)}),
  updateDownloadProfile: (id: number, payload: Partial<Omit<DownloadProfileInput, 'collection_id'>>) => request(`/api/profiles/downloads/${id}`, DownloadProfile, {method: 'PUT', body: JSON.stringify(payload)}),
  deleteDownloadProfile: (id: number) => requestVoid(`/api/profiles/downloads/${id}`, {method: 'DELETE'}),

  streamProfiles: (collectionId?: number) => request(`/api/profiles/streams${collectionId ? `?collection_id=${collectionId}` : ''}`, z.array(StreamProfile)),
  createStreamProfile: (payload: StreamProfileInput) => request('/api/profiles/streams', StreamProfile, {method: 'POST', body: JSON.stringify(payload)}),
  updateStreamProfile: (id: number, payload: Partial<Omit<StreamProfileInput, 'collection_id'>>) => request(`/api/profiles/streams/${id}`, StreamProfile, {method: 'PUT', body: JSON.stringify(payload)}),
  deleteStreamProfile: (id: number) => requestVoid(`/api/profiles/streams/${id}`, {method: 'DELETE'}),

  tasks: () => request('/api/tasks?limit=100', z.array(TaskRun)),
  taskLedger: (page = 1, pageSize = 50) => request(`/api/tasks/ledger?page=${page}&page_size=${pageSize}`, TaskLedger),
  taskDefinitions: () => request('/api/tasks/definitions', z.array(TaskDefinition)),
  taskSchedules: () => request('/api/tasks/schedules', z.array(TaskSchedule)),
  taskOperations: () => request('/api/tasks/operations', z.array(TaskOperation)),
  cancelTask: (id: number) => request(`/api/tasks/${id}/cancel`, z.object({status: z.string(), run_id: z.number()}), {method: 'POST'}),
  prioritizeTask: (id: number) => request(`/api/tasks/${id}/prioritize`, z.object({status: z.string(), run_id: z.number()}), {method: 'POST'}),
  triggerTask: (taskKey: string, resourceType: string, resourceId: number) => request('/api/tasks/trigger', TaskRun, {method: 'POST', body: JSON.stringify({task_key: taskKey, resource_type: resourceType, resource_id: resourceId, payload: {}})}),
  createTaskSchedule: (payload: TaskScheduleInput) => request('/api/tasks/schedules', TaskSchedule, {method: 'POST', body: JSON.stringify(payload)}),
  updateTaskSchedule: (id: number, payload: Partial<Omit<TaskScheduleInput, 'task_key'>>) => request(`/api/tasks/schedules/${id}`, TaskSchedule, {method: 'PUT', body: JSON.stringify(payload)}),
  deleteTaskSchedule: (id: number) => requestVoid(`/api/tasks/schedules/${id}`, {method: 'DELETE'}),
}
