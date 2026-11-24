import {z} from 'zod'
import {CollectionWordsSchema} from './collection_contract'

/** The kinds of issue the collection health check finds, as a collection stores them in its health. */
export const HealthIssueKindSchema = z.enum(['moves'])
export type HealthIssueKind = z.infer<typeof HealthIssueKindSchema>

/** Downloads that the collection's season settings put in another season, which wait for its Move action. */
export const MovesIssueSchema = z.object({
    kind: z.literal('moves'),
    count: z.number(),
    /** Why they move: what the collection's settings make its seasons now, in words. */
    seasonsPlan: z.string(),
})

/** What one kind of issue tells the user. */
export const HealthIssueSchema = z.discriminatedUnion('kind', [MovesIssueSchema])
export type HealthIssue = z.infer<typeof HealthIssueSchema>

/** A collection that needs the user, with what for. */
export const UnhealthyCollectionSchema = z.object({
    slug: z.string(),
    title: z.string(),
    /** What it calls its seasons and episodes. */
    words: CollectionWordsSchema,
    issues: z.array(HealthIssueSchema),
})
export type UnhealthyCollection = z.infer<typeof UnhealthyCollectionSchema>
