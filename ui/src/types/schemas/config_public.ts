/**
 * Subset of the backend VODLoft settings
 *
 * Only exposes things here that React might actually need (ignores secrets or backend-only config)
 */
import {z} from 'zod'

export const _PublicSessionConfigSchema = z.object({
    ttlSeconds: z.int(),
})

export const _PublicAdminAuthSchema = z.object({
    enabled: z.boolean(),
})

export const _PublicUserAccountsSchema = z.object({
    enabled: z.boolean(),
})

export const ConfigPublicSchema = z.object({
    appVersion: z.string(),
    loginSession: _PublicSessionConfigSchema,
    adminAuth: _PublicAdminAuthSchema,
    userAccounts: _PublicUserAccountsSchema,
})
export type ConfigPublic = z.infer<typeof ConfigPublicSchema>