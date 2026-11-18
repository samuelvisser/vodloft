import {z} from 'zod'
import {IndexingValueEntrySchema} from './custom_metadata'

import {PreferredFormatReg, CollectionLocalMediaProfileScopeReg, EpisodeNfoReg} from '../local_media_profile'
import {
    LocalMediaProfileCreateBaseSchema,
    LocalMediaProfileOutputTemplateSchema,
    LocalMediaProfileSchemaRequest,
    LocalMediaProfileSchemaResponse,
    LocalMediaProfileUpdateBaseSchema,
    LocalMediaProfileSubtitleModeSchema,
} from './local_media_profile_base'


export const COLLECTION_LOCAL_MEDIA_PROFILE_INDEXING_VALUES_MAX_ITEMS = 100

export const CollectionLocalMediaProfileIndexingValuesSchema = z.array(IndexingValueEntrySchema)
    .max(
        COLLECTION_LOCAL_MEDIA_PROFILE_INDEXING_VALUES_MAX_ITEMS,
        `At most ${COLLECTION_LOCAL_MEDIA_PROFILE_INDEXING_VALUES_MAX_ITEMS} Indexing Values are allowed`,
    )
    .superRefine((indexingValues, ctx) => {
        const seen = new Set<string>()
        indexingValues.forEach(({key}, index) => {
            if (seen.has(key)) {
                ctx.addIssue({
                    code: 'custom',
                    path: [index, 'key'],
                    message: 'Keys must be unique',
                })
            }
            seen.add(key)
        })
    })


/** The templates that give each episode the title and description the site gives it. */
export const SITE_TITLE_TEMPLATE = '{{ title }}'
export const SITE_DESCRIPTION_TEMPLATE = '{{ description }}'

// ---------- Strict request (create/update) ----------
const CollectionLocalMediaProfileBaseSchema = LocalMediaProfileSchemaRequest.extend({
    type: z.enum(['collection', 'music']).default('collection'),
    collectionScope: z.enum(CollectionLocalMediaProfileScopeReg.values).default('both'),
    outputTemplate: LocalMediaProfileOutputTemplateSchema.default(
        '/downloads/shows/{{ collection }}/{{ episode_title }}.ext',
    ),
    preferredFormat: z.enum(PreferredFormatReg.values).default('format_audio_only'),
    downloadCollectionAssets: z.boolean().nullable().default(null),
    showNfo: z.boolean().default(false),
    episodeNfo: z.enum(EpisodeNfoReg.values).default('episode'),
    /** Jinja templates for each episode's title and description in its metadata; empty keeps the site's. */
    episodeTitleTemplate: z.string().max(1000).nullable().default(SITE_TITLE_TEMPLATE),
    episodeDescriptionTemplate: z.string().max(4000).nullable().default(SITE_DESCRIPTION_TEMPLATE),
    indexingValues: CollectionLocalMediaProfileIndexingValuesSchema.default([]),
})

export const CollectionLocalMediaProfileCreateSchema = CollectionLocalMediaProfileBaseSchema.safeExtend({
    ...LocalMediaProfileCreateBaseSchema.shape,
    subtitleMode: LocalMediaProfileSubtitleModeSchema.default('sidecar'),
})
export type CollectionLocalMediaProfileCreateIn = z.input<typeof CollectionLocalMediaProfileCreateSchema>
export type CollectionLocalMediaProfileCreateOut = z.output<typeof CollectionLocalMediaProfileCreateSchema>

export const CollectionLocalMediaProfileUpdateSchema = CollectionLocalMediaProfileBaseSchema.safeExtend({
    ...LocalMediaProfileUpdateBaseSchema.shape,
    subtitleMode: LocalMediaProfileSubtitleModeSchema.default('sidecar'),
})
export type CollectionLocalMediaProfileUpdateIn = z.input<typeof CollectionLocalMediaProfileUpdateSchema>
export type CollectionLocalMediaProfileUpdateOut = z.output<typeof CollectionLocalMediaProfileUpdateSchema>


// ------------ Lenient response (read) ------------
export const CollectionLocalMediaProfileReadSchema = LocalMediaProfileSchemaResponse.safeExtend({
    type: z.enum(['collection', 'music']),
    collectionScope: z.enum(CollectionLocalMediaProfileScopeReg.values)
        .nullable()
        .optional()
        .transform((value) => value ?? 'both'),
    downloadCollectionAssets: z.boolean().nullable().default(null),
    showNfo: z.boolean().default(false),
    episodeNfo: z.enum(EpisodeNfoReg.values).default('episode'),
    // A profile without its own keeps the site's, which these templates show.
    episodeTitleTemplate: z.string().nullable().default(null).transform((value) => value ?? SITE_TITLE_TEMPLATE),
    episodeDescriptionTemplate: z.string().nullable().default(null).transform((value) => value ?? SITE_DESCRIPTION_TEMPLATE),
    indexingValues: z.array(IndexingValueEntrySchema).default([]),
})
export type CollectionLocalMediaProfileRead = z.infer<typeof CollectionLocalMediaProfileReadSchema>
