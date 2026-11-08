import {z} from 'zod'

/** One page of a profile table: the rows, how many profiles its filters leave, and how to continue. */
export function profilePageSchema<T extends z.ZodType>(item: T) {
    return z.object({
        items: item.array(),
        limit: z.int().positive(),
        total: z.int().nonnegative(),
        nextCursor: z.string().nullable().optional(),
        previousCursor: z.string().nullable().optional(),
        hasMore: z.boolean(),
    })
}
