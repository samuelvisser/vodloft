import {z} from 'zod'
import {Collection, SourceInspection, Video} from './schemas'

async function request<T>(path: string, schema: z.ZodType<T>, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {headers: {'Content-Type': 'application/json'}, ...init})
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail ?? response.statusText)
  return schema.parse(await response.json())
}

export const api = {
  collections: () => request('/api/library/collections', z.array(Collection)),
  videos: () => request('/api/library/videos', z.array(Video)),
  inspect: (url: string) => request('/api/library/inspect', SourceInspection, {method: 'POST', body: JSON.stringify({url})}),
  addVideo: (url: string) => request('/api/library/videos', Video, {method: 'POST', body: JSON.stringify({url})}),
  addCollection: (url: string, kind?: 'channel' | 'playlist') => request('/api/library/collections', Collection, {method: 'POST', body: JSON.stringify({url, kind})}),
}
