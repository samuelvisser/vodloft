import {z} from 'zod'

import {ApiDateTimeSchema} from './datetime'
import {SourcedFields} from './source'


export const VideoReadSchema = z.looseObject({
    id: z.int(),
    uuid: z.string(),
    slug: z.string(),
    title: z.string(),
    description: z.string().nullable(),
    duration: z.number(),
    drmProtected: z.boolean(),
    needsSubscription: z.boolean().optional().default(false),
    sharingUrl: z.string(),
    authorName: z.string().nullable(),
    authorUrl: z.string().nullable(),
    publishedAt: ApiDateTimeSchema.nullable(),
    backgroundImagePath: z.string().nullable(),
    thumbnailLandscapePath: z.string().nullable(),
    thumbnailPortraitPath: z.string().nullable(),
    thumbnailSquarePath: z.string().nullable(),
    ...SourcedFields,
    createdAt: ApiDateTimeSchema,
    updatedAt: ApiDateTimeSchema,
})
export type VideoRead = z.infer<typeof VideoReadSchema>
