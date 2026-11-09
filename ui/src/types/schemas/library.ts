import {z} from 'zod'
import {LibraryCollectionSortReg} from '../collection'

/** How many collections, movies and videos the library holds. */
export const LibraryCountsSchema = z.object({
    collections: z.int().nonnegative(),
    movies: z.int().nonnegative(),
    videos: z.int().nonnegative(),
})

export type LibraryCounts = z.infer<typeof LibraryCountsSchema>

/** How the signed-in user lists the Library; ``saved`` is false without user accounts, when the browser keeps it. */
export const LibraryPreferencesSchema = z.object({
    collectionSort: z.enum(LibraryCollectionSortReg.values),
    collectionSortReversed: z.boolean(),
    saved: z.boolean(),
})

export type LibraryPreferences = z.infer<typeof LibraryPreferencesSchema>
