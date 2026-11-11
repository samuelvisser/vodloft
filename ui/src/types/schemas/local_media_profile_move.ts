import {z} from 'zod'

export const EpisodeMoveOutcomeSchema = z.enum([
    'move', 'replace', 'target_has_file', 'path_taken', 'same_path', 'file_missing', 'busy',
])
export type EpisodeMoveOutcome = z.infer<typeof EpisodeMoveOutcomeSchema>

export const LocalMediaProfileMoveEpisodeSchema = z.looseObject({
    mediaDownloadId: z.int(),
    episodeId: z.int(),
    episodeSlug: z.string(),
    episodeTitle: z.string(),
    outcome: EpisodeMoveOutcomeSchema,
    sourcePath: z.string(),
    destinationPath: z.string().nullish(),
})
export type LocalMediaProfileMoveEpisode = z.infer<typeof LocalMediaProfileMoveEpisodeSchema>

export const LocalMediaProfileMoveDownloadProfileSchema = z.looseObject({
    id: z.int(),
    enableProfile: z.boolean(),
    deleteOlderEpisodes: z.boolean(),
})

export const LocalMediaProfileMoveCollectionSchema = z.looseObject({
    collectionId: z.int(),
    collectionSlug: z.string(),
    collectionTitle: z.string(),
    inScope: z.boolean(),
    /** Whether the target is for this type of Collection. */
    typeOffered: z.boolean(),
    /** Whether the target is offered for the Collection's Site. */
    siteOffered: z.boolean(),
    blocked: z.boolean(),
    canMoveDownloadProfile: z.boolean(),
    retentionAtRisk: z.int(),
    sourceDownloadProfiles: z.array(LocalMediaProfileMoveDownloadProfileSchema),
    targetDownloadProfiles: z.array(LocalMediaProfileMoveDownloadProfileSchema),
    episodes: z.array(LocalMediaProfileMoveEpisodeSchema),
})
export type LocalMediaProfileMoveCollection = z.infer<typeof LocalMediaProfileMoveCollectionSchema>

export const LocalMediaProfileMovePreviewSchema = z.looseObject({
    target: z.looseObject({id: z.int(), slug: z.string(), name: z.string()}),
    collections: z.array(LocalMediaProfileMoveCollectionSchema),
})
export type LocalMediaProfileMovePreview = z.infer<typeof LocalMediaProfileMovePreviewSchema>
