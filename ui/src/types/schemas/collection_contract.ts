import {z} from 'zod'

/** A word as the backend names it: one, many, and one with its article, such as album, albums and an album. */
export const NamesSchema = z.object({one: z.string(), many: z.string(), a: z.string()})

export const CollectionWordsSchema = z.object({season: NamesSchema, episode: NamesSchema})

/** One collection type's words, for episodes of video and for episodes of sound only. */
export const CollectionContractSchema = z.object({
    type: z.string(),
    words: CollectionWordsSchema,
    audioWords: CollectionWordsSchema,
})

/** Every collection type's contract, and VODLoft's own words where no type is meant. */
export const CollectionContractsSchema = z.object({
    words: CollectionWordsSchema,
    types: z.array(CollectionContractSchema),
})
export type CollectionContracts = z.infer<typeof CollectionContractsSchema>
