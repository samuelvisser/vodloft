import {z} from 'zod'
import {LEVELS, SourceLimitSchema} from '../../lib/access'

export const UserReadSchema = z.object({
    id: z.number(),
    username: z.string(),
    enabled: z.boolean(),
    mustChangePassword: z.boolean(),
    templateKey: z.string().nullable(),
    administrator: z.boolean(),
    levels: z.record(z.string(), z.enum(LEVELS)),
    sources: z.array(SourceLimitSchema).nullable(),
    membersOnly: z.boolean(),
    deleteFiles: z.boolean(),
    createdBy: z.string().nullable(),
    createdAt: z.coerce.date(),
    lastLoginAt: z.coerce.date().nullable(),
})
export type UserRead = z.infer<typeof UserReadSchema>

export const UserAccountsSettingsReadSchema = z.object({
    enabled: z.boolean(),
    environmentPassword: z.boolean(),
    administrators: z.number(),
})
export type UserAccountsSettingsRead = z.infer<typeof UserAccountsSettingsReadSchema>

export const AccessOptionsReadSchema = z.object({
    areas: z.array(z.object({area: z.string(), levels: z.array(z.enum(LEVELS))})),
    templates: z.array(z.object({
        key: z.string(),
        name: z.string(),
        levels: z.record(z.string(), z.enum(LEVELS)),
        deleteFiles: z.boolean(),
    })),
})
export type AccessOptionsRead = z.infer<typeof AccessOptionsReadSchema>
export type AccessTemplate = AccessOptionsRead['templates'][number]

/** A user's access list as the user editor sends it. */
export type UserAccessInput = {
    templateKey: string | null
    levels: Record<string, string>
    sources: Array<{sourceKey: string, domains: string[] | null}> | null
    membersOnly: boolean
    deleteFiles: boolean
}
