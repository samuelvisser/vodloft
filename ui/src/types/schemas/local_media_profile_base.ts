import {z} from 'zod'
import {ApiDateTimeSchema} from "./datetime";


export const LocalMediaProfileStorageModeSchema = z.enum(['system', 'direct', 'temporary'])
export type LocalMediaProfileStorageMode = z.infer<typeof LocalMediaProfileStorageModeSchema>
export const LocalMediaProfileThumbnailModeSchema = z.enum([
    'system',
    'no_thumbnail',
    'embed',
    'sidecar',
    'embed_and_sidecar',
])
export type LocalMediaProfileThumbnailMode = z.infer<typeof LocalMediaProfileThumbnailModeSchema>
export const LocalMediaProfileMetadataModeSchema = z.enum([
    'system',
    'no_metadata',
    'embed',
    'nfo',
    'embed_and_nfo',
])
export type LocalMediaProfileMetadataMode = z.infer<typeof LocalMediaProfileMetadataModeSchema>
export const LocalMediaProfileSubtitleModeSchema = z.enum([
    'no_subtitles', 'embed', 'sidecar', 'embed_and_sidecar',
])
export type LocalMediaProfileSubtitleMode = z.infer<typeof LocalMediaProfileSubtitleModeSchema>


export const VideoCodecChoiceSchema = z.object({
    codec: z.enum(['av1', 'vp9', 'h264', 'h265']),
    allowed: z.boolean(),
})
export const LanguageCodeSchema = z.string().regex(/^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$/, 'Use a language code such as en or pt-BR')

/** Quality and subtitle language choices, with the defaults of a new profile. */
const QualityAndLanguageFields = {
    subtitleLanguages: z.array(LanguageCodeSchema).max(20).default(['en']),
    subtitleLanguageMode: z.enum(['listed', 'first', 'site']).default('listed'),
    qualityGoal: z.enum(['compatibility', 'quality', 'small', 'custom']).default('compatibility'),
    videoCodecs: z.array(VideoCodecChoiceSchema).default([
        {codec: 'h264', allowed: true}, {codec: 'av1', allowed: false},
        {codec: 'vp9', allowed: false}, {codec: 'h265', allowed: false},
    ]).refine((codecs) => codecs.some((choice) => choice.allowed), 'Allow at least one video codec'),
    codecFallback: z.enum(['best', 'skip']).default('best'),
    container: z.enum(['mp4', 'mkv']).default('mp4'),
    audioCodec: z.enum(['aac', 'opus']).default('aac'),
    audioFormat: z.enum(['m4a', 'opus', 'mp3']).default('m4a'),
    audioLanguage: LanguageCodeSchema.nullable().default(null),
}

// ---------- Strict request (create/update) ----------
export const LocalMediaProfileSchemaRequest = z.object({
    name: z.string().min(1, 'Name is required'),
    downloadMode: LocalMediaProfileStorageModeSchema.default('system'),
    thumbnailMode: LocalMediaProfileThumbnailModeSchema.default('system'),
    metadataMode: LocalMediaProfileMetadataModeSchema.default('system'),
    subtitleMode: LocalMediaProfileSubtitleModeSchema.default('sidecar'),
    /** The Sources the profile is offered for; null offers it for every Source, including ones added later. */
    sourceKeys: z.array(z.string()).min(1, 'Choose at least one Source').nullable().default(null),
    ...QualityAndLanguageFields,
})

export const LocalMediaProfileCreateBaseSchema = LocalMediaProfileSchemaRequest

export const LocalMediaProfileUpdateBaseSchema = LocalMediaProfileSchemaRequest.extend({
    id: z.int(),
    slug: z.string(),
})

const SINGLE_BRACE_OUTPUT_TEMPLATE_VARIABLE = /(^|[^{])\{\s*[A-Za-z_][A-Za-z0-9_]*\s*\}(?!\})/

export const LocalMediaProfileOutputTemplateSchema = z.string()
    .refine(
        (value) => /\.ext$/.test(value) || /\.ext\s*{%[-]?\s*endif\s*[-]?%}$/.test(value),
        {message: "Each output path must end with '.ext'"},
    )
    .refine(
        (value) => !SINGLE_BRACE_OUTPUT_TEMPLATE_VARIABLE.test(value),
        {message: "Output template variables must use Jinja syntax such as '{{ collection }}'; single-brace variables are not supported"},
    )
    .min(16)
    .max(4096)


// ------------ Lenient response (read) ------------
export const LocalMediaProfileSchemaResponse = z.looseObject({
    id: z.int(),
    slug: z.string(),
    name: z.string(),
    outputTemplate: z.string(),
    preferredFormat: z.string(),
    downloadMode: LocalMediaProfileStorageModeSchema.default('system'),
    thumbnailMode: LocalMediaProfileThumbnailModeSchema.default('system'),
    metadataMode: LocalMediaProfileMetadataModeSchema.default('system'),
    subtitleMode: LocalMediaProfileSubtitleModeSchema.default('sidecar'),
    ...QualityAndLanguageFields,
    sourceKeys: z.array(z.string()).nullable().optional().transform((value) => value ?? null),
    createdAt: ApiDateTimeSchema,
    updatedAt: ApiDateTimeSchema,
})
