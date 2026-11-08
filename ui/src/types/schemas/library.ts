import {z} from 'zod'

/** How many collections, movies and videos the library holds. */
export const LibraryCountsSchema = z.object({
    collections: z.int().nonnegative(),
    movies: z.int().nonnegative(),
    videos: z.int().nonnegative(),
})

export type LibraryCounts = z.infer<typeof LibraryCountsSchema>
