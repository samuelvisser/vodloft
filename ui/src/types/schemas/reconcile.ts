import {z} from 'zod'
import {CollectionWordsSchema} from './collection_contract'
import {NamesSchema} from './source'

/** The videos of one list that move to another season of their collection. */
export const MovedPartSchema = z.object({
    /** What they are of, such as the list that holds them in their new season. */
    label: z.string(),
    names: NamesSchema,
    count: z.number(),
    toSeason: z.string(),
    /** The titles of the videos, newest first, up to a few dozen. */
    examples: z.array(z.string()),
    /** Downloads whose files move along into their new season. */
    filesMoved: z.number().default(0),
})
export type MovedPart = z.infer<typeof MovedPartSchema>

/** What the Move action does to a collection. */
export const MovePreviewSchema = z.object({
    slug: z.string(),
    title: z.string(),
    type: z.string(),
    episodeIdentifier: z.string(),
    parts: z.array(MovedPartSchema),
    /** It can number its episodes again: not when it numbers them by date. */
    renumberOffered: z.boolean(),
    changes: z.array(z.object({title: z.string(), before: z.string(), after: z.string()})),
    profiles: z.array(z.object({name: z.string(), filesRenamed: z.number(), metadataRewritten: z.number()})),
    /** Files moved, so its files are renamed and their metadata rewritten also when it keeps its numbers. */
    filesFollow: z.boolean(),
})
export type MovePreview = z.infer<typeof MovePreviewSchema>

/** Where an episode is after its Move action moved it. */
export const ReconcileResultSchema = z.object({
    episodeSlug: z.string().nullable().optional(),
    collectionSlug: z.string().nullable().optional(),
})
export type ReconcileResult = z.infer<typeof ReconcileResultSchema>

/** A collection whose Moved episodes wait for its Move action. */
export const MovesWaitingSchema = z.object({
    slug: z.string(),
    title: z.string(),
    moved: z.number(),
    /** What it calls its seasons and episodes. */
    words: CollectionWordsSchema,
})
export type MovesWaiting = z.infer<typeof MovesWaitingSchema>
