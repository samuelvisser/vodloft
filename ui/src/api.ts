import {z} from 'zod'
import {Collection, DownloadProfile, SourceInspection, Task, Video} from './schemas'

async function request<T>(path: string, schema: z.ZodType<T>, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {headers: {'Content-Type': 'application/json'}, ...init})
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail ?? response.statusText)
  if (response.status === 204) return undefined as T
  return schema.parse(await response.json())
}

export const api = {
  collections: () => request('/api/library/collections', z.array(Collection)),
  videos: () => request('/api/library/videos?standalone_only=true', z.array(Video)),
  downloadProfiles: () => request('/api/profiles/downloads', z.array(DownloadProfile)),
  tasks: () => request('/api/tasks', z.array(Task)),
  inspect: (url: string) => request('/api/library/inspect', SourceInspection, {method: 'POST', body: JSON.stringify({url})}),
  addVideo: (url: string) => request('/api/library/videos', Video, {method: 'POST', body: JSON.stringify({url})}),
  addCollection: (url: string, kind?: 'channel' | 'playlist') => request('/api/library/collections', Collection, {method: 'POST', body: JSON.stringify({url, kind})}),
  syncCollection: (id: number) => request(`/api/library/collections/${id}/sync`, Task, {method: 'POST'}),
  downloadVideo: (id: number, profileId: number) => request(`/api/library/videos/${id}/download?profile_id=${profileId}`, Task, {method: 'POST'}),
}
