import {z} from 'zod'
import {CollectionWordsSchema} from './collection_contract'
import {NamesSchema} from './source'

/** The checks of the collection health check, each by the kind of issue it finds. */
export const HealthIssueKindSchema = z.enum(['moves', 'new_lists', 'creators'])
export type HealthIssueKind = z.infer<typeof HealthIssueKindSchema>

/** How much a message on Home asks of the user. */
export const HealthLevelSchema = z.enum(['error', 'warning', 'info'])
export type HealthLevel = z.infer<typeof HealthLevelSchema>

/** Downloads that the collection's season settings put in another season, which wait for its Move action. */
export const MovesIssueSchema = z.object({
    kind: z.literal('moves'),
    level: HealthLevelSchema,
    count: z.number(),
    /** Why they move: what the collection's settings make its seasons now, in words. */
    seasonsPlan: z.string(),
})

/** Lists the collection's channel added later, which wait for the user's choice in its Seasons dialog. */
export const NewListsIssueSchema = z.object({
    kind: z.literal('new_lists'),
    level: HealthLevelSchema,
    count: z.number(),
    /** What the collection calls its lists, such as playlists. */
    names: NamesSchema,
})

/** What one kind of issue tells the user. */
export const HealthIssueSchema = z.discriminatedUnion('kind', [MovesIssueSchema, NewListsIssueSchema])
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

/** Several collections of one creator that are in no creator yet, which the user can group under the creator. */
export const CreatorSuggestionSchema = z.object({
    kind: z.literal('creators'),
    level: HealthLevelSchema,
    siteKey: z.string(),
    ref: z.string(),
    /** The creator's name. */
    title: z.string(),
    /** What the Site calls its creators. */
    creatorNames: NamesSchema,
    siteName: z.string(),
    collections: z.array(z.object({slug: z.string(), title: z.string()})),
    /** The creator in the Library already, when they are: the collections join them. */
    creatorSlug: z.string().nullable().optional(),
    creatorTitle: z.string().nullable().optional(),
})
export type CreatorSuggestion = z.infer<typeof CreatorSuggestionSchema>

/** What the collection health check found that needs the user. */
export const LibraryHealthSchema = z.object({
    collections: z.array(UnhealthyCollectionSchema),
    creatorSuggestions: z.array(CreatorSuggestionSchema),
})
export type LibraryHealth = z.infer<typeof LibraryHealthSchema>

/** The checks of the collection health check, which are on, and how many suggestions the user put away. */
export const HealthChecksSchema = z.object({
    checks: z.array(z.object({kind: HealthIssueKindSchema, title: z.string(), on: z.boolean()})),
    dismissed: z.number(),
})
export type HealthChecks = z.infer<typeof HealthChecksSchema>
