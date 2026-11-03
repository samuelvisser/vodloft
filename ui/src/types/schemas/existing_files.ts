import {z} from 'zod'

export const ExistingFileEpisodeSchema = z.looseObject({
    id: z.int(),
    slug: z.string(),
    title: z.string(),
    date: z.string().nullish(),
    collectionSlug: z.string(),
    collectionTitle: z.string(),
})
export type ExistingFileEpisode = z.infer<typeof ExistingFileEpisodeSchema>

export const ExistingFileConfidenceSchema = z.enum(['certain', 'likely', 'review'])
export type ExistingFileConfidence = z.infer<typeof ExistingFileConfidenceSchema>

export const ExistingFileSchema = z.looseObject({
    path: z.string(),
    size: z.number(),
    episode: ExistingFileEpisodeSchema.nullish(),
    matchedBy: z.string().nullish(),
    confidence: ExistingFileConfidenceSchema.nullish(),
    candidates: z.array(ExistingFileEpisodeSchema).default([]),
    note: z.string().nullish(),
    adopted: z.boolean().default(false),
})
export type ExistingFile = z.infer<typeof ExistingFileSchema>

export const ExistingFilesCountsSchema = z.looseObject({
    certain: z.int(),
    likely: z.int(),
    review: z.int(),
    unmatched: z.int(),
    adopted: z.int(),
})
export type ExistingFilesCounts = z.infer<typeof ExistingFilesCountsSchema>

export const ExistingFilesStatusSchema = z.enum(['none', 'waiting', 'scanning', 'ready', 'failed', 'finished'])
export type ExistingFilesStatus = z.infer<typeof ExistingFilesStatusSchema>

export const ExistingFilesScanSchema = z.looseObject({
    status: ExistingFilesStatusSchema,
    error: z.string().nullish(),
    folder: z.string().nullish(),
    template: z.string().nullish(),
    defaultFolder: z.string(),
    localMediaProfileId: z.int(),
    heldDownloadProfiles: z.int().default(0),
    counts: ExistingFilesCountsSchema.nullish(),
    episodesWithoutFile: z.int().default(0),
    files: z.array(ExistingFileSchema).default([]),
})
export type ExistingFilesScan = z.infer<typeof ExistingFilesScanSchema>

export const ExistingFilesScanSummarySchema = z.looseObject({
    status: ExistingFilesStatusSchema,
    localMediaProfileId: z.int(),
    heldDownloadProfiles: z.int().default(0),
    counts: ExistingFilesCountsSchema,
})
export type ExistingFilesScanSummary = z.infer<typeof ExistingFilesScanSummarySchema>

export const ExistingFilesOpenScanSchema = ExistingFilesScanSummarySchema.extend({
    collectionSlug: z.string(),
    collectionTitle: z.string(),
    localMediaProfileName: z.string(),
    folder: z.string(),
    error: z.string().nullish(),
})
export type ExistingFilesOpenScan = z.infer<typeof ExistingFilesOpenScanSchema>

export const ExistingFilesProfileReviewSchema = z.looseObject({
    status: ExistingFilesStatusSchema,
    folder: z.string(),
    localMediaProfileId: z.int(),
    heldDownloadProfiles: z.int().default(0),
    counts: ExistingFilesCountsSchema,
    episodesWithoutFile: z.int().default(0),
    files: z.array(ExistingFileSchema).default([]),
    collections: z.array(z.looseObject({
        collectionSlug: z.string(),
        collectionTitle: z.string(),
        status: ExistingFilesStatusSchema,
    })).default([]),
})
export type ExistingFilesProfileReview = z.infer<typeof ExistingFilesProfileReviewSchema>

export const FolderListSchema = z.looseObject({
    folder: z.string(),
    parent: z.string().nullish(),
    folders: z.array(z.string()),
})
export type FolderList = z.infer<typeof FolderListSchema>
