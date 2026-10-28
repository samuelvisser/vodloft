import {z} from 'zod'

import {VideoPreferredFormatReg} from '../local_media_profile'
import {
    LocalMediaProfileCreateBaseSchema,
    LocalMediaProfileOutputTemplateSchema,
    LocalMediaProfileSchemaRequest,
    LocalMediaProfileSchemaResponse,
    LocalMediaProfileSubtitleModeSchema,
    LocalMediaProfileUpdateBaseSchema,
} from './local_media_profile_base'


export const DEFAULT_VIDEO_OUTPUT_TEMPLATE = (
    "{% set output_date = date ~ ' - ' if date %}"
    + '/downloads/videos/{{ author or source }}/'
    + '{{ output_date }}{{ title }} [{{ slug }}].ext'
)

// ---------- Strict request (create/update) ----------
const VideoLocalMediaProfileBaseSchema = LocalMediaProfileSchemaRequest.extend({
    type: z.literal('video').default('video'),
    outputTemplate: LocalMediaProfileOutputTemplateSchema.default(DEFAULT_VIDEO_OUTPUT_TEMPLATE),
    preferredFormat: z.enum(VideoPreferredFormatReg.values).default('format_1080p'),
})

// Single videos come from yt-dlp, which VODLoft does not fetch subtitles for yet.
export const VideoLocalMediaProfileCreateSchema = VideoLocalMediaProfileBaseSchema.extend({
    ...LocalMediaProfileCreateBaseSchema.shape,
    subtitleMode: LocalMediaProfileSubtitleModeSchema.default('no_subtitles'),
})
export type VideoLocalMediaProfileCreateIn = z.input<typeof VideoLocalMediaProfileCreateSchema>
export type VideoLocalMediaProfileCreateOut = z.output<typeof VideoLocalMediaProfileCreateSchema>

export const VideoLocalMediaProfileUpdateSchema = VideoLocalMediaProfileBaseSchema.extend(
    LocalMediaProfileUpdateBaseSchema.shape,
)
export type VideoLocalMediaProfileUpdateIn = z.input<typeof VideoLocalMediaProfileUpdateSchema>
export type VideoLocalMediaProfileUpdateOut = z.output<typeof VideoLocalMediaProfileUpdateSchema>


// ------------ Lenient response (read) ------------
export const VideoLocalMediaProfileReadSchema = LocalMediaProfileSchemaResponse.safeExtend({
    type: z.literal('video'),
})
export type VideoLocalMediaProfileRead = z.infer<typeof VideoLocalMediaProfileReadSchema>
