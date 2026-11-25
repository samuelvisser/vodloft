import {z} from 'zod'
import {NamesSchema} from './source'

/** One setting change that made downloads wait for the Move action, as it was and is now, by where it is changed. */
export const MoveCauseSchema = z.object({
    origin: z.enum(['seasons']),
    setting: z.string(),
    before: z.union([z.string(), z.array(z.string())]).nullable(),
    after: z.union([z.string(), z.array(z.string())]).nullable(),
    /** For a setting of one thing in the collection, such as one of its lists: that thing. */
    subjectId: z.number().nullable().default(null),
    subjectTitle: z.string().nullable().default(null),
})
export type MoveCause = z.infer<typeof MoveCauseSchema>
export type MoveCauseOrigin = MoveCause['origin']

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
    /** The setting changes that made them wait, in the order they were made; none when VODLoft recorded none. */
    causes: z.array(MoveCauseSchema),
    /** What the collection's settings make its seasons now, in words: why they move when no change was recorded. */
    seasonsPlan: z.string(),
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
