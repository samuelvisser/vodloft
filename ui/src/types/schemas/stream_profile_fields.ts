import {z} from 'zod'
import {PreferredFormatReg} from '../local_media_profile'
import {ApiDateTimeSchema} from './datetime'

// ---------- What every stream profile type has ----------
export const StreamProfileFieldsSchema = z.object({
    title: z.string().trim().min(1),
    enableProfile: z.boolean().default(true),
    useDownloads: z.boolean().default(true),
    useSourceStream: z.boolean().default(true),
    preferredFormat: z.enum(PreferredFormatReg.values).refine(
        (value) => value !== 'format_hls',
        {message: 'HLS is a Local Media Profile download format, not a Stream Profile preferred format'},
    ),
    preferExactMatch: z.boolean().default(false),
    epIdTypeList: z.array(z.string()).default(['ep', 'aux']),
    streamLiveEpisodes: z.boolean().default(false),
    proxySourceStream: z.boolean().default(true),
    maxItems: z.int().nonnegative().default(100),
})

export const StreamProfileFieldsReadSchema = z.looseObject({
    id: z.int(),
    collectionId: z.int(),
    enableProfile: z.boolean(),
    useDownloads: z.boolean(),
    useSourceStream: z.boolean(),
    preferredFormat: z.union([z.enum(PreferredFormatReg.values), z.string()]),
    preferExactMatch: z.boolean(),
    epIdTypeList: z.array(z.string()),
    streamLiveEpisodes: z.boolean(),
    proxySourceStream: z.boolean(),
    maxItems: z.number(),
    effectiveTitle: z.string(),
    createdAt: ApiDateTimeSchema,
    updatedAt: ApiDateTimeSchema,
})
