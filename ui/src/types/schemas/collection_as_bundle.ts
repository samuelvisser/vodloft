import {CollectionCreatePayloadSchema} from './collection'
import {DownloadProfileSchemaRequest} from './download_profile'
import {CollectionLocalMediaProfileCreateSchema} from './collection_local_media_profile'
import {RssStreamProfileBundleSchema} from './rss_stream_profile'
import {z} from 'zod'
import {SeasonDetachedSchema} from './season'


// The add-show wizard supplies the starting filters, which follow the collection's seasons and Source.
export const DownloadProfileBundleSchema = DownloadProfileSchemaRequest
export type DownloadProfileBundleIn = z.input<typeof DownloadProfileBundleSchema>
export type DownloadProfileBundleOut = z.output<typeof DownloadProfileBundleSchema>


export const LocalMediaProfileCreateUnionSchema = CollectionLocalMediaProfileCreateSchema.safeExtend({
    op: z.literal('create_new').default('create_new'),
})
export type LocalMediaProfileCreateUnionIn = z.input<typeof LocalMediaProfileCreateUnionSchema>
export type LocalMediaProfileCreateUnionOut = z.output<typeof LocalMediaProfileCreateUnionSchema>


// The wizard uses an existing profile as it is: other collections share it, so it is changed on its own page.
export const LocalMediaProfileUseExistingSchema = z.object({
    op: z.literal('use_existing').default('use_existing'),
    slug: z.string().min(1),
})
export type LocalMediaProfileUseExistingIn = z.input<typeof LocalMediaProfileUseExistingSchema>
export type LocalMediaProfileUseExistingOut = z.output<typeof LocalMediaProfileUseExistingSchema>


export const LocalMediaProfileChoiceSchema = z.discriminatedUnion('op', [
    LocalMediaProfileCreateUnionSchema,
    LocalMediaProfileUseExistingSchema,
])
export type LocalMediaProfileChoiceIn = z.input<typeof LocalMediaProfileChoiceSchema>
export type LocalMediaProfileChoiceOut = z.output<typeof LocalMediaProfileChoiceSchema>


export {RssStreamProfileBundleSchema}
export type RssStreamProfileBundleIn = z.input<typeof RssStreamProfileBundleSchema>
export type RssStreamProfileBundleOut = z.output<typeof RssStreamProfileBundleSchema>


export const CollectionCreateBundleSchema = z.object({
    collection: CollectionCreatePayloadSchema,
    seasons: z.array(SeasonDetachedSchema),
    localMediaProfile: LocalMediaProfileChoiceSchema.optional(),
    downloadProfile: DownloadProfileBundleSchema.optional(),
    streamProfile: RssStreamProfileBundleSchema.optional(),
})
export type CollectionCreateBundleIn = z.input<typeof CollectionCreateBundleSchema>
export type CollectionCreateBundleOut = z.output<typeof CollectionCreateBundleSchema>
