import {z} from 'zod'
import {
  Collection, DownloadProfile, LocalMediaProfile, SourceInspection, StreamProfile, StreamTarget, Task, Video,
} from './schemas'

async function request<T>(path: string, schema: z.ZodType<T>, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {headers: {'Content-Type': 'application/json'}, ...init})
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail ?? response.statusText)
  return schema.parse(await response.json())
}

async function requestVoid(path: string, init?: RequestInit): Promise<void> {
  const response = await fetch(path, init)
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail ?? response.statusText)
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

export const api = {
  collections: () => request('/api/library/collections', z.array(Collection)),
  videos: () => request('/api/library/videos?standalone_only=true', z.array(Video)),
  localProfiles: (scope?: 'collection' | 'video') => request(`/api/profiles/local-media${scope ? `?scope=${scope}` : ''}`, z.array(LocalMediaProfile)),
  downloadProfiles: (collectionId?: number) => request(`/api/profiles/downloads${collectionId ? `?collection_id=${collectionId}` : ''}`, z.array(DownloadProfile)),
  streamProfiles: (collectionId?: number) => request(`/api/profiles/streams${collectionId ? `?collection_id=${collectionId}` : ''}`, z.array(StreamProfile)),
  tasks: () => request('/api/tasks', z.array(Task)),
  inspect: (url: string) => request('/api/library/inspect', SourceInspection, {method: 'POST', body: JSON.stringify({url})}),
  addVideo: (url: string) => request('/api/library/videos', Video, {method: 'POST', body: JSON.stringify({url})}),
  addCollection: (url: string, kind?: 'channel' | 'playlist') => request('/api/library/collections', Collection, {method: 'POST', body: JSON.stringify({url, kind})}),
  syncCollection: (id: number) => request(`/api/library/collections/${id}/sync`, Task, {method: 'POST'}),
  downloadVideo: (id: number, localMediaProfileId: number) => request(`/api/library/videos/${id}/download`, Task, {method: 'POST', body: JSON.stringify({local_media_profile_id: localMediaProfileId})}),
  resolveStream: (videoId: number, profileId: number) => request(`/api/library/videos/${videoId}/stream?profile_id=${profileId}`, StreamTarget),
  createLocalProfile: (payload: LocalMediaProfileInput) => request('/api/profiles/local-media', LocalMediaProfile, {method: 'POST', body: JSON.stringify(payload)}),
  deleteLocalProfile: (id: number) => requestVoid(`/api/profiles/local-media/${id}`, {method: 'DELETE'}),
  createDownloadProfile: (payload: {name: string; collection_id: number; local_media_profile_id: number; enable_profile: boolean}) => request('/api/profiles/downloads', DownloadProfile, {method: 'POST', body: JSON.stringify(payload)}),
  deleteDownloadProfile: (id: number) => requestVoid(`/api/profiles/downloads/${id}`, {method: 'DELETE'}),
  createStreamProfile: (payload: {name: string; collection_id: number; enable_profile: boolean; use_downloads: boolean; format_selector: string}) => request('/api/profiles/streams', StreamProfile, {method: 'POST', body: JSON.stringify(payload)}),
  deleteStreamProfile: (id: number) => requestVoid(`/api/profiles/streams/${id}`, {method: 'DELETE'}),
}
