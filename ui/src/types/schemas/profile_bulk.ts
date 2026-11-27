import {z} from 'zod'

/** Every profile a table's filters match, for Select all in bulk edit. */
export const ProfileIdsSchema = z.object({
    ids: z.int().array(),
})

const BulkValueCountSchema = z.object({
    value: z.union([z.string(), z.number(), z.boolean()]).nullable(),
    count: z.int(),
})

export const BulkFieldSummarySchema = z.object({
    offered: z.int(),
    sitesWithout: z.string().array(),
    values: BulkValueCountSchema.array(),
})

/** What the chosen profiles are set to now, by setting. A table can send more, such as settings that depend on what
 * the chosen items have, which it reads itself. */
export const BulkSummarySchema = z.looseObject({
    count: z.int(),
    fields: z.record(z.string(), BulkFieldSummarySchema),
})
export type BulkSummary = z.infer<typeof BulkSummarySchema>

/** How many profiles a bulk change or delete did, and the ones it left alone with why. */
export const BulkResultSchema = z.object({
    done: z.int(),
    skipped: z.object({
        id: z.int(),
        name: z.string(),
        reason: z.string(),
    }).array(),
})
export type BulkResult = z.infer<typeof BulkResultSchema>
