import {CollectionCreatePayloadSchema} from './collection'
import {DownloadProfileSchemaRequest, refineDownloadLimit} from './download_profile'
import {
    CollectionLocalMediaProfileCreateSchema,
    CollectionLocalMediaProfileUpdateSchema,
} from './collection_local_media_profile'
import {RssStreamProfileCreateSchema} from './rss_stream_profile'
import {z} from 'zod'
import {SeasonDetachedSchema} from './season'


export const DownloadProfileBundleSchema = DownloadProfileSchemaRequest.extend({
    // The add-show wizard supplies the latest available season dynamically.
    // Keep this required here so getZodDefaults can distinguish an untouched
    // wizard profile from one where the user deliberately cleared all seasons.
    seasons: z.array(SeasonDetachedSchema),
}).superRefine(refineDownloadLimit)
export type DownloadProfileBundleIn = z.input<typeof DownloadProfileBundleSchema>
export type DownloadProfileBundleOut = z.output<typeof DownloadProfileBundleSchema>


export const LocalMediaProfileCreateUnionSchema = CollectionLocalMediaProfileCreateSchema.safeExtend({
    op: z.literal('create_new').default('create_new'),
})
export type LocalMediaProfileCreateUnionIn = z.input<typeof LocalMediaProfileCreateUnionSchema>
export type LocalMediaProfileCreateUnionOut = z.output<typeof LocalMediaProfileCreateUnionSchema>


export const LocalMediaProfileUpdateUnionSchema = CollectionLocalMediaProfileUpdateSchema.safeExtend({
    op: z.literal('update_by_slug').default('update_by_slug'),
})
export type LocalMediaProfileUpdateUnionIn = z.input<typeof LocalMediaProfileUpdateUnionSchema>
export type LocalMediaProfileUpdateUnionOut = z.output<typeof LocalMediaProfileUpdateUnionSchema>


export const LocalMediaProfileUpsertSchema = z.discriminatedUnion('op', [
    LocalMediaProfileCreateUnionSchema,
    LocalMediaProfileUpdateUnionSchema,
])
export type LocalMediaProfileUpsertIn = z.input<typeof LocalMediaProfileUpsertSchema>
export type LocalMediaProfileUpsertOut = z.output<typeof LocalMediaProfileUpsertSchema>


export const RssStreamProfileBundleSchema = RssStreamProfileCreateSchema.omit({collectionId: true})
export type RssStreamProfileBundleIn = z.input<typeof RssStreamProfileBundleSchema>
export type RssStreamProfileBundleOut = z.output<typeof RssStreamProfileBundleSchema>


export const CollectionCreateBundleSchema = z.object({
    collection: CollectionCreatePayloadSchema,
    seasons: z.array(SeasonDetachedSchema),
    localMediaProfile: LocalMediaProfileUpsertSchema.optional(),
    downloadProfile: DownloadProfileBundleSchema.optional(),
    streamProfile: RssStreamProfileBundleSchema.optional(),
})
export type CollectionCreateBundleIn = z.input<typeof CollectionCreateBundleSchema>
export type CollectionCreateBundleOut = z.output<typeof CollectionCreateBundleSchema>
