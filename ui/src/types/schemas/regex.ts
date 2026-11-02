import {z} from 'zod'

export const RegexSampleSchema = z.object({
    text: z.string(),
    matched: z.boolean(),
    spans: z.array(z.tuple([z.number(), z.number()])),
    timedOut: z.boolean(),
    own: z.boolean(),
    publishedAt: z.string().nullable().optional(),
})
export type RegexSample = z.infer<typeof RegexSampleSchema>

export const RegexCheckSchema = z.object({
    pattern: z.string(),
    ignoreCase: z.boolean(),
    valid: z.boolean(),
    error: z.string().nullable().optional(),
    errorPosition: z.number().nullable().optional(),
    samples: z.array(RegexSampleSchema),
    collectionTotal: z.number(),
    collectionMatches: z.number(),
})
export type RegexCheck = z.infer<typeof RegexCheckSchema>
