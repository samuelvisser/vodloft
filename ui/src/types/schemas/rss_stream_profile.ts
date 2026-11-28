import {z} from 'zod'
import {RssVideoOutputModeReg} from "../stream_profile";
import {StreamProfileFieldsReadSchema, StreamProfileFieldsSchema} from './stream_profile_fields'

// ---------- Strict request (create/update) ----------
const RssStreamProfileBaseSchema = StreamProfileFieldsSchema.extend({
    videoOutputMode: z.enum(RssVideoOutputModeReg.values).nullable().default(null),
})

const validateVideoOutput = (
    value: {preferredFormat: string; videoOutputMode: string | null; streamLiveEpisodes: boolean},
    ctx: z.RefinementCtx,
) => {
    const audioOnly = value.preferredFormat === 'format_audio_only'

    if (audioOnly && value.videoOutputMode !== null) {
        ctx.addIssue({
            code: 'custom',
            path: ['videoOutputMode'],
            message: 'Audio-only Stream Profiles cannot have a video output mode',
        })
    }
    if (!audioOnly && value.videoOutputMode === null) {
        ctx.addIssue({
            code: 'custom',
            path: ['videoOutputMode'],
            message: 'Video Stream Profiles require a video output mode',
        })
    }

    if (!value.streamLiveEpisodes) return
    if (audioOnly) {
        ctx.addIssue({
            code: 'custom',
            path: ['streamLiveEpisodes'],
            message: 'Live episode streaming requires a video preferred format',
        })
        return
    }
    if (value.videoOutputMode === null || !['audio_hls', 'mp4_hls'].includes(value.videoOutputMode)) {
        ctx.addIssue({
            code: 'custom',
            path: ['streamLiveEpisodes'],
            message: 'Live episode streaming requires an HLS video output mode',
        })
    }
}

const RssStreamProfileCreateFieldsSchema = RssStreamProfileBaseSchema.extend({
    collectionId: z.int(),
    feedUrl: z.string().optional(),
})

export const RssStreamProfileCreateSchema = RssStreamProfileCreateFieldsSchema.superRefine(validateVideoOutput)
export type RssStreamProfileCreateIn = z.input<typeof RssStreamProfileCreateSchema>
export type RssStreamProfileCreateOut = z.output<typeof RssStreamProfileCreateSchema>

// Sent together with its new collection, which has no id yet. Zod only omits keys before refining.
export const RssStreamProfileBundleSchema = RssStreamProfileCreateFieldsSchema
    .omit({collectionId: true})
    .superRefine(validateVideoOutput)

export const RssStreamProfileUpdateSchema = RssStreamProfileBaseSchema.extend({
    feedUrl: z.string().min(1),
}).superRefine(validateVideoOutput)
export type RssStreamProfileUpdateIn = z.input<typeof RssStreamProfileUpdateSchema>
export type RssStreamProfileUpdateOut = z.output<typeof RssStreamProfileUpdateSchema>

export const RssStreamProfileReadSchema = StreamProfileFieldsReadSchema.extend({
    type: z.literal('rss'),
    videoOutputMode: z.union([z.enum(RssVideoOutputModeReg.values), z.string()]).nullable(),
    feedUrl: z.string(),
})
export type RssStreamProfileRead = z.infer<typeof RssStreamProfileReadSchema>
