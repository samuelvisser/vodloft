import {z} from 'zod'
import {NamesSchema} from './source'

export const CollectionWordsSchema = z.object({season: NamesSchema, episode: NamesSchema})

/** One collection type's words, for episodes of video and for episodes of sound only. */
export const CollectionContractSchema = z.object({
    type: z.string(),
    words: CollectionWordsSchema,
    audioWords: CollectionWordsSchema,
    /** What a collection of the type calls the creator behind it, such as artist; null where it is the Site's word. */
    creatorNames: NamesSchema.nullable(),
    /** Downloads pick the collection's seasons; otherwise its newest episodes, by days or a number of episodes. */
    downloadsBySeason: z.boolean(),
})

/** Every collection type's contract, and VODLoft's own words where no type is meant. */
export const CollectionContractsSchema = z.object({
    words: CollectionWordsSchema,
    types: z.array(CollectionContractSchema),
})
export type CollectionContracts = z.infer<typeof CollectionContractsSchema>
