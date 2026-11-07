import { ConfigPublic, ConfigPublicSchema } from '../types/schemas/config_public'
import {apiUrl} from './api'

export async function loadPublicConfig(): Promise<ConfigPublic> {
  const base = apiUrl()
  const r = await fetch(`${base}/config/public`, { credentials: 'include' })
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  const json = await r.json()
  const parsed = ConfigPublicSchema.parse(json)
  ;(window as any).publicConfig = parsed
  return parsed
}

export function getPublicConfig(): ConfigPublic | undefined {
  return (window as any).publicConfig as ConfigPublic | undefined
}
