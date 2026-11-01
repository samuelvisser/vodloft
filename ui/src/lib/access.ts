/**
 * What the signed-in person may see and change, from GET /auth/me.
 *
 * Loaded once before the app renders; signing in, out or changing password
 * reloads the page, so it does not change while a page is open. Hiding
 * something here is only a convenience: the API refuses it anyway.
 */
import { z } from 'zod'

export const AREAS = [
  'library',
  'add_media',
  'managed_downloads',
  'quick_downloads',
  'download_profiles',
  'local_media_profiles',
  'stream_profiles',
  'tasks',
  'logs',
  'settings',
  'sources',
  'users',
] as const
export type Area = (typeof AREAS)[number]

export const LEVELS = ['none', 'view', 'manage'] as const
export type Level = (typeof LEVELS)[number]

const LEVEL_RANK: Record<Level, number> = { none: 0, view: 1, manage: 2 }

export const SourceLimitSchema = z.object({
  sourceKey: z.string(),
  domains: z.array(z.string()).nullable(),
})
export type SourceLimit = z.infer<typeof SourceLimitSchema>

export const AuthMeSchema = z.object({
  accountsEnabled: z.boolean(),
  recovery: z.boolean(),
  user: z
    .object({
      id: z.number(),
      username: z.string(),
      templateKey: z.string().nullable(),
      mustChangePassword: z.boolean(),
    })
    .nullable(),
  levels: z.record(z.string(), z.enum(LEVELS)),
  administrator: z.boolean(),
  sources: z.array(SourceLimitSchema).nullable(),
  membersOnly: z.boolean(),
  deleteFiles: z.boolean(),
})
export type AuthMe = z.infer<typeof AuthMeSchema>

let current: AuthMe | null = null
let checked = false

/** Ask the API who is signed in. ``null`` when nobody is (401). */
export async function loadAccess(): Promise<AuthMe | null> {
  const base = (window as any).appConfig?.API_URL || '/api'
  const response = await fetch(`${base}/auth/me`, { credentials: 'include' })
  if (response.status === 401) {
    current = null
    checked = true
    return null
  }
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  current = AuthMeSchema.parse(await response.json())
  checked = true
  return current
}

export function getAccess(): AuthMe | null {
  return current
}

/** Whether the API has answered who is signed in, even if nobody is. */
export function accessChecked(): boolean {
  return checked
}

/** For tests. */
export function setAccess(access: AuthMe | null) {
  current = access
}

export function levelOf(access: AuthMe | null, area: Area): Level {
  return access?.levels[area] ?? 'none'
}

export function allows(access: AuthMe | null, area: Area, level: Level = 'view'): boolean {
  // Until a one-time password is replaced, the API refuses everything else.
  if (access?.user?.mustChangePassword) return false
  return LEVEL_RANK[levelOf(access, area)] >= LEVEL_RANK[level]
}

/** ``can('library', 'manage')`` for the signed-in person. */
export function can(area: Area, level: Level = 'view'): boolean {
  return allows(current, area, level)
}

export function canUseSource(sourceKey: string): boolean {
  return current?.sources == null || current.sources.some((limit) => limit.sourceKey === sourceKey)
}

/** The Settings page; its Sources and Users tabs also need their own areas. */
export function canAnySettings(access: AuthMe | null = current): boolean {
  return allows(access, 'settings', 'manage')
}

/** The page to open first: the first area this person may see, in sidebar order. */
export function homePath(access: AuthMe | null = current): string {
  if (allows(access, 'library')) return '/'
  const candidates: Array<[Area, string]> = [
    ['quick_downloads', '/quick-download'],
    ['managed_downloads', '/downloads'],
    ['add_media', '/browse'],
    ['local_media_profiles', '/local-media-profiles'],
    ['download_profiles', '/download-profiles'],
    ['stream_profiles', '/stream-profiles'],
    ['tasks', '/tasks'],
    ['logs', '/logs'],
  ]
  const found = candidates.find(([area]) => allows(access, area))
  if (found) return found[1]
  return canAnySettings(access) ? '/settings' : '/account'
}

export function useAccess() {
  const access = current
  return {
    access,
    can: (area: Area, level: Level = 'view') => allows(access, area, level),
    canUseSource,
    signedInUser: access?.user ?? null,
  }
}
