import {z} from 'zod'

import {ApiDateTimeSchema} from './datetime'

/** How much an open state asks of the user: Home lists problems first. */
export const SeveritySchema = z.enum(['problem', 'needs_you', 'tip', 'news'])
export type Severity = z.infer<typeof SeveritySchema>

/** Something on Home that stays until it is fixed or answered. */
export const AttentionReadSchema = z.object({
    id: z.number(),
    kind: z.string(),
    severity: SeveritySchema,
    title: z.string(),
    body: z.string(),
    url: z.string().nullable(),
    collectionId: z.number().nullable(),
    openedAt: ApiDateTimeSchema,
})
export type AttentionRead = z.infer<typeof AttentionReadSchema>
