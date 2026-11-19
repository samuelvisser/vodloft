import {z} from 'zod'

import {VideoLocalMediaProfileScopeReg, VideoPreferredFormatReg} from '../local_media_profile'
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

/** A template for a Video profile made for movies: a folder per movie, with its extras beside it. */
export const DEFAULT_MOVIE_OUTPUT_TEMPLATE = (
    "/downloads/movies/{{ movie_title }}/{{ title }}{% if media_type != 'movie' %}-{{ media_type }}{% endif %}.ext"
)

// ---------- Strict request (create/update) ----------
const VideoLocalMediaProfileBaseSchema = LocalMediaProfileSchemaRequest.extend({
    type: z.literal('video').default('video'),
    videoScope: z.enum(VideoLocalMediaProfileScopeReg.values).default('both'),
    outputTemplate: LocalMediaProfileOutputTemplateSchema.default(DEFAULT_VIDEO_OUTPUT_TEMPLATE),
    preferredFormat: z.enum(VideoPreferredFormatReg.values).default('format_1080p'),
})

// New Video profiles start without subtitles; they can be turned on like any other profile.
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
    videoScope: z.enum(VideoLocalMediaProfileScopeReg.values).default('both'),
})
export type VideoLocalMediaProfileRead = z.infer<typeof VideoLocalMediaProfileReadSchema>
