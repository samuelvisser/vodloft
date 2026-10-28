import {z} from 'zod'
import {ApiDateTimeSchema} from './datetime'
import {TaskOperationReadSchema} from './operation'
import {ResolvedLinkReadSchema} from './source'

export const QUICK_QUALITIES = [2160, 1440, 1080, 720, 480] as const
export const QUICK_CODECS = ['h264', 'h265', 'vp9', 'av1'] as const
export const MP3_BITRATES = [320, 192, 128] as const

export type QuickQuality = typeof QUICK_QUALITIES[number]
export type QuickCodec = typeof QUICK_CODECS[number]
export type Mp3Bitrate = typeof MP3_BITRATES[number]

export type QuickChoice = {
    kind: 'video' | 'audio'
    /** A height; null is Best. */
    quality: QuickQuality | null
    container: 'mp4' | 'mkv'
    /** null is Auto. */
    codec: QuickCodec | null
    audioFormat: 'm4a' | 'mp3'
    audioBitrate: Mp3Bitrate | null
    embedMetadata: boolean
    embedArtwork: boolean
}

const QuickCodecOptionSchema = z.object({
    codec: z.string(),
    sizeBytes: z.number().nullable().optional(),
})

export const QuickVideoOptionSchema = z.object({
    quality: z.number().nullable().optional(),
    sizeBytes: z.number().nullable().optional(),
    codec: z.string().nullable().optional(),
    codecs: z.array(QuickCodecOptionSchema).default([]),
})
export type QuickVideoOption = z.infer<typeof QuickVideoOptionSchema>

export const QuickAudioOptionSchema = z.object({
    audioFormat: z.enum(['m4a', 'mp3']),
    bitrate: z.number().nullable().optional(),
    sizeBytes: z.number().nullable().optional(),
})
export type QuickAudioOption = z.infer<typeof QuickAudioOptionSchema>

export const QuickDownloadOptionsSchema = z.object({
    link: ResolvedLinkReadSchema,
    refused: z.string().nullable().optional(),
    formatChoices: z.boolean(),
    containers: z.array(z.string()),
    videos: z.array(QuickVideoOptionSchema),
    audio: z.array(QuickAudioOptionSchema),
    duration: z.number().nullable().optional(),
})
export type QuickDownloadOptions = z.infer<typeof QuickDownloadOptionsSchema>

export const QuickDownloadReadySchema = z.object({
    id: z.string(),
    title: z.string(),
    fileName: z.string(),
    sizeBytes: z.number(),
    format: z.string(),
    state: z.enum(['ready', 'delivered']),
    createdAt: ApiDateTimeSchema,
    expiresAt: ApiDateTimeSchema,
    deliveredAt: ApiDateTimeSchema.nullable().optional(),
    sourceKey: z.string().nullable().optional(),
    sourceName: z.string().nullable().optional(),
    url: z.string().nullable().optional(),
    kind: z.string().nullable().optional(),
})
export type QuickDownloadReady = z.infer<typeof QuickDownloadReadySchema>

export const QuickDownloadsSchema = z.object({
    active: z.array(TaskOperationReadSchema),
    ready: z.array(QuickDownloadReadySchema),
})
export type QuickDownloads = z.infer<typeof QuickDownloadsSchema>

export const QuickDownloadAcceptedSchema = z.looseObject({
    operationId: z.string(),
    quickDownloadId: z.string(),
})
