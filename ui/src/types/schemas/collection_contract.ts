import {z} from 'zod'
import {NamesSchema} from './source'

export const CollectionWordsSchema = z.object({season: NamesSchema, episode: NamesSchema, inSeason: z.string()})

/** One collection type's words, for episodes of video and for episodes of sound only. */
export const CollectionContractSchema = z.object({
    type: z.string(),
    words: CollectionWordsSchema,
    audioWords: CollectionWordsSchema,
    /** What a collection of the type calls the creator behind it, such as artist; null where it is the Site's word. */
    creatorNames: NamesSchema.nullable(),
    /** What the season of what is in none of a collection's lists is called, such as Singles; null for the Site's. */
    looseSeason: z.string().nullable(),
    /** What a new Local Media Profile for a collection of the type keeps, such as podcast. */
    profileScope: z.string(),
    /** What a Local Media Profile can keep to be offered for a collection of the type. */
    profileScopes: z.array(z.string()),
    /** Downloads pick the collection's seasons; otherwise its newest episodes, by days or a number of episodes. */
    downloadsBySeason: z.boolean(),
})

/** Every collection type's contract, and VODLoft's own words where no type is meant. */
export const CollectionContractsSchema = z.object({
    words: CollectionWordsSchema,
    types: z.array(CollectionContractSchema),
})
export type CollectionContracts = z.infer<typeof CollectionContractsSchema>
