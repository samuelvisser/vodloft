import {z} from 'zod'

/** Every profile a table's filters match, for Select all in bulk edit. */
export const ProfileIdsSchema = z.object({
    ids: z.int().array(),
})

const BulkValueCountSchema = z.object({
    value: z.union([z.string(), z.number(), z.boolean()]).nullable(),
    count: z.int(),
})

/** What the chosen profiles are set to now, by setting. */
export const BulkSummarySchema = z.object({
    count: z.int(),
    fields: z.record(z.string(), z.object({
        offered: z.int(),
        values: BulkValueCountSchema.array(),
    })),
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
