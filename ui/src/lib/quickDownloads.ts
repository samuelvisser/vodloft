import {useQuery} from '@tanstack/react-query'
import {QuickDownloadSettingsSchema} from '../types/schemas/settings'
import {z} from 'zod'
import {
    MP3_BITRATES,
    QUICK_QUALITIES,
    QuickAudioOption,
    QuickChoice,
    QuickCodec,
    QuickDownloadAcceptedSchema,
    QuickDownloadHistoryEntrySchema,
    QuickDownloadOptions,
    QuickDownloadOptionsSchema,
    QuickDownloadsSchema,
    QuickQuality,
    QuickVideoOption,
    Mp3Bitrate,
} from '../types/schemas/quick_download'
import type {QuickDownloadSettings} from '../types/schemas/settings'
import type {TaskOperationRead} from '../types/schemas/operation'
import {formatBytes} from '../utils/formatting'
import {apiUrl, responseError, apiJson} from './api'

export const QUICK_DOWNLOAD_OPERATION_KIND = 'quick.download'
export const quickDownloadsQueryKey = ['quickDownloads'] as const
const ACTIVE_QUICK_DOWNLOAD_STATUSES = new Set(['QUEUED', 'RUNNING', 'WAITING'])

/**
 * The quick downloads still queued or working, among the operations the frontend receives:
 * the ones working first, then the queue, each oldest first, as on Downloads.
 */
export function activeQuickDownloads(operations: readonly TaskOperationRead[]): TaskOperationRead[] {
    const queued = (operation: TaskOperationRead) => operation.status === 'QUEUED' ? 1 : 0
    return operations
        .filter((operation) => operation.kind === QUICK_DOWNLOAD_OPERATION_KIND && ACTIVE_QUICK_DOWNLOAD_STATUSES.has(operation.status))
        .sort((left, right) => queued(left) - queued(right) || (left.createdAt ?? '').localeCompare(right.createdAt ?? ''))
}

export const CODEC_NAMES: Record<QuickCodec, string> = {h264: 'H.264', h265: 'H.265', vp9: 'VP9', av1: 'AV1'}
export const CODEC_NOTES: Record<QuickCodec, string> = {
    h264: 'plays everywhere',
    h265: 'smaller, newer devices',
    vp9: 'smaller, newer devices',
    av1: 'smallest, newest devices',
}

/** Look a link up, with what it can be quick downloaded as. */
export async function fetchQuickDownloadOptions(url: string, signal?: AbortSignal, sourceKey?: string): Promise<QuickDownloadOptions> {
    const response = await fetch(`${apiUrl()}/quick-downloads/options`, {
        method: 'POST',
        credentials: 'include',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(sourceKey ? {url, sourceKey} : {url}),
        signal,
    })
    if (!response.ok) throw await responseError(response)
    return QuickDownloadOptionsSchema.parse(await response.json())
}

export const QuickDownloadPreviewSchema = z.object({
    sourceKey: z.string(),
    title: z.string(),
    imageUrl: z.string().nullable().optional(),
    authorName: z.string().nullable().optional(),
    site: z.string().nullable().optional(),
})
export type QuickDownloadPreview = z.infer<typeof QuickDownloadPreviewSchema>

/**
 * A link's title and thumbnail from a faster lookup than the options, to show
 * while they load. Null when there is none or anything goes wrong: the options
 * lookup reports problems.
 */
export async function fetchQuickDownloadPreview(url: string, signal?: AbortSignal, sourceKey?: string): Promise<QuickDownloadPreview | null> {
    try {
        const response = await fetch(`${apiUrl()}/quick-downloads/preview`, {
            method: 'POST',
            credentials: 'include',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(sourceKey ? {url, sourceKey} : {url}),
            signal,
        })
        if (!response.ok) return null
        const body = await response.json()
        return body == null ? null : QuickDownloadPreviewSchema.parse(body)
    } catch {
        return null
    }
}

export async function startQuickDownload(url: string, sourceKey: string, choice: QuickChoice) {
    const response = await fetch(`${apiUrl()}/quick-downloads`, {
        method: 'POST',
        credentials: 'include',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({url, sourceKey, choice}),
    })
    if (!response.ok) throw await responseError(response)
    return QuickDownloadAcceptedSchema.parse(await response.json())
}

export async function removeQuickDownload(quickId: string): Promise<void> {
    const response = await fetch(`${apiUrl()}/quick-downloads/${encodeURIComponent(quickId)}`, {
        method: 'DELETE',
        credentials: 'include',
    })
    if (!response.ok && response.status !== 404) throw await responseError(response)
}

export function quickDownloadFileUrl(quickId: string): string {
    return `${apiUrl()}/quick-downloads/${encodeURIComponent(quickId)}/file`
}

export const quickDownloadHistoryQueryKey = ['quickDownloads', 'history'] as const

export function useQuickDownloadHistory(enabled = true) {
    return useQuery({
        queryKey: quickDownloadHistoryQueryKey,
        enabled,
        queryFn: async ({signal}) => {
            const response = await fetch(`${apiUrl()}/quick-downloads/history`, {signal, credentials: 'include'})
            if (!response.ok) throw await responseError(response)
            return z.array(QuickDownloadHistoryEntrySchema).parse(await response.json())
        },
        refetchInterval: 60_000,
    })
}

export async function clearQuickDownloadHistory(): Promise<void> {
    const response = await fetch(`${apiUrl()}/quick-downloads/history`, {method: 'DELETE', credentials: 'include'})
    if (!response.ok) throw await responseError(response)
}

/** A choice stored in the history, back in the shape the page uses. Unknown values fall back to the defaults. */
export function choiceFromHistory(stored: Record<string, unknown>, defaults: QuickChoice): QuickChoice {
    const pick = <T>(value: unknown, allowed: readonly T[], fallback: T): T => allowed.includes(value as T) ? value as T : fallback
    return {
        kind: pick(stored.kind, ['video', 'audio'] as const, defaults.kind),
        quality: pick(stored.quality ?? null, [null, ...QUICK_QUALITIES] as const, defaults.quality),
        container: pick(stored.container, ['mp4', 'mkv'] as const, defaults.container),
        codec: pick(stored.codec ?? null, [null, 'h264', 'h265', 'vp9', 'av1'] as const, defaults.codec),
        audioFormat: pick(stored.audio_format, ['m4a', 'mp3'] as const, defaults.audioFormat),
        audioBitrate: pick(stored.audio_bitrate ?? null, [null, ...MP3_BITRATES] as const, defaults.audioBitrate),
        embedMetadata: typeof stored.embed_metadata === 'boolean' ? stored.embed_metadata : defaults.embedMetadata,
        embedArtwork: typeof stored.embed_artwork === 'boolean' ? stored.embed_artwork : defaults.embedArtwork,
    }
}

const QuickDownloadSettingsForUserSchema = QuickDownloadSettingsSchema.extend({
    /** The defaults are the user's own, saved to their account, not the install's. */
    ownDefaults: z.boolean().default(false),
})
export type QuickDownloadSettingsForUser = z.infer<typeof QuickDownloadSettingsForUserSchema>

export const quickDownloadSettingsQueryKey = ['quickDownloadSettings'] as const

/** Settings › Quick download, readable by everyone who may quick download, with the user's own defaults. */
export function useQuickDownloadSettings() {
    return useQuery({
        queryKey: quickDownloadSettingsQueryKey,
        queryFn: async ({signal}) => {
            return apiJson(`/quick-downloads/settings`, QuickDownloadSettingsForUserSchema.parse, {signal})
        },
        staleTime: 60_000,
    })
}

/** Save a choice as the user's own defaults, or with ``null`` go back to the install's. */
export async function saveQuickDownloadPreferences(choice: QuickChoice | null): Promise<QuickDownloadSettingsForUser> {
    const response = await fetch(`${apiUrl()}/quick-downloads/preferences`, {
        method: choice ? 'PUT' : 'DELETE',
        credentials: 'include',
        headers: choice ? {'Content-Type': 'application/json'} : undefined,
        body: choice ? JSON.stringify(settingsFromChoice(choice)) : undefined,
    })
    if (!response.ok) throw await responseError(response)
    return QuickDownloadSettingsForUserSchema.parse(await response.json())
}

export function useQuickDownloads() {
    return useQuery({
        queryKey: quickDownloadsQueryKey,
        queryFn: async ({signal}) => {
            return apiJson(`/quick-downloads`, QuickDownloadsSchema.parse, {signal})
        },
        // Ready files count down to their deletion. A delivered file reaches
        // the page as a quick.delivered operation through the frontend puller.
        refetchInterval: 30_000,
        refetchOnMount: 'always',
    })
}

/** The choice the page starts with, from Settings › Quick download. */
export function choiceFromSettings(settings?: QuickDownloadSettings): QuickChoice {
    const quality = settings?.defaultQuality && settings.defaultQuality !== 'best'
        ? Number.parseInt(settings.defaultQuality, 10) as QuickQuality
        : null
    return {
        kind: settings?.defaultKind ?? 'video',
        quality: settings ? quality : 1080,
        container: settings?.defaultContainer ?? 'mp4',
        codec: settings && settings.defaultCodec !== 'auto' ? settings.defaultCodec : null,
        audioFormat: settings?.defaultAudioFormat ?? 'm4a',
        audioBitrate: (MP3_BITRATES as readonly number[]).includes(settings?.defaultMp3Bitrate ?? 0)
            ? settings!.defaultMp3Bitrate as Mp3Bitrate
            : 192,
        embedMetadata: settings?.embedMetadata ?? true,
        embedArtwork: settings?.embedArtwork ?? true,
    }
}

/** The settings values that make a choice the default next time. */
export function settingsFromChoice(choice: QuickChoice): Partial<QuickDownloadSettings> {
    return {
        defaultKind: choice.kind,
        defaultQuality: choice.quality ? `${choice.quality}p` as QuickDownloadSettings['defaultQuality'] : 'best',
        defaultContainer: choice.container,
        defaultCodec: choice.codec ?? 'auto',
        defaultAudioFormat: choice.audioFormat,
        defaultMp3Bitrate: choice.audioBitrate ?? 192,
        embedMetadata: choice.embedMetadata,
        embedArtwork: choice.embedArtwork,
    }
}

/**
 * Fit a choice to what a link offers: the closest quality at or below the
 * wanted one, and only what the Source can make.
 */
export function fitChoice(choice: QuickChoice, options: QuickDownloadOptions): QuickChoice {
    if (!options.formatChoices) {
        choice = {...choice, container: 'mp4', codec: null, audioFormat: 'm4a', audioBitrate: null}
        if (!options.qualityChoices) return {...choice, quality: null}
    }
    const qualities = options.videos.map((video) => video.quality ?? null).filter((q): q is number => q != null)
    let quality = choice.quality
    if (quality != null && !qualities.includes(quality)) {
        quality = (qualities.find((q) => q <= quality!) ?? qualities[qualities.length - 1] ?? null) as QuickQuality | null
    }
    return {...choice, quality}
}

export function videoOption(options: QuickDownloadOptions, quality: number | null): QuickVideoOption | undefined {
    return options.videos.find((video) => (video.quality ?? null) === quality)
}

export function audioOption(options: QuickDownloadOptions, choice: QuickChoice): QuickAudioOption | undefined {
    if (choice.audioFormat === 'mp3') return options.audio.find((a) => a.audioFormat === 'mp3' && a.bitrate === (choice.audioBitrate ?? 320))
    return options.audio.find((a) => a.audioFormat === 'm4a')
}

/** The codec a video row gives with this choice, when it is offered. */
export function codecSize(video: QuickVideoOption, codec: QuickCodec | null): number | null | undefined {
    if (codec == null) return video.sizeBytes
    return video.codecs.find((c) => c.codec === codec)?.sizeBytes
}

export function choiceSize(options: QuickDownloadOptions, choice: QuickChoice): number | null | undefined {
    if (choice.kind === 'audio') return audioOption(options, choice)?.sizeBytes
    const video = videoOption(options, choice.quality)
    return video ? codecSize(video, choice.codec) : undefined
}

export function qualityLabel(quality: number | null | undefined): string {
    if (quality == null) return 'Best'
    if (quality === 2160) return '4K · 2160p'
    return `${quality}p`
}

/** A short name for a choice, as the Download button and the footer show it. */
export function choiceSummary(choice: QuickChoice): string {
    if (choice.kind === 'audio') {
        return choice.audioFormat === 'mp3' ? `MP3 ${choice.audioBitrate ?? 320} kbps` : 'Audio M4A'
    }
    const quality = choice.quality ? `${choice.quality}p` : 'Best'
    return `${quality} ${choice.container.toUpperCase()}${choice.codec ? ` · ${CODEC_NAMES[choice.codec]}` : ''}`
}

export function sizeLabel(size: number | null | undefined): string {
    return size ? formatBytes(size) : ''
}

export function isKnownQuality(value: number): value is QuickQuality {
    return (QUICK_QUALITIES as readonly number[]).includes(value)
}

/** The rules in Settings › Quick download, as the page applies them. The server checks them again. */
export type QuickRules = {
    maxQuality: number | null
    allowed: ReadonlySet<string>
    fixedCodec: QuickCodec | null
    maxBytes: number | null
    maxDurationSeconds: number | null
    allowedSources: readonly string[] | null
    locked: boolean
}

export const NO_RULES: QuickRules = {
    maxQuality: null, allowed: new Set(['mp4', 'mkv', 'm4a', 'mp3']), fixedCodec: null, maxBytes: null,
    maxDurationSeconds: null, allowedSources: null, locked: false,
}

export function rulesFromSettings(settings?: QuickDownloadSettings): QuickRules {
    if (!settings) return NO_RULES
    const allowed = new Set<string>()
    if (settings.allowMp4) allowed.add('mp4')
    if (settings.allowMkv) allowed.add('mkv')
    if (settings.allowM4a) allowed.add('m4a')
    if (settings.allowMp3) allowed.add('mp3')
    const sources = settings.allowedSources.split(',').map((key) => key.trim()).filter(Boolean)
    return {
        maxQuality: settings.maxQuality === 'best' ? null : Number.parseInt(settings.maxQuality, 10),
        allowed,
        fixedCodec: settings.fixedCodec === 'auto' ? null : settings.fixedCodec,
        maxBytes: settings.maxFileGigabytes > 0 ? settings.maxFileGigabytes * 1024 ** 3 : null,
        maxDurationSeconds: settings.maxDurationMinutes > 0 ? settings.maxDurationMinutes * 60 : null,
        allowedSources: sources.length ? sources : null,
        locked: settings.lockToDefaults,
    }
}

/** Why a quality row cannot be picked under the rules, or null. */
export function qualityBlocked(quality: number | null | undefined, rules: QuickRules): string | null {
    if (quality != null && rules.maxQuality != null && quality > rules.maxQuality) return `above the ${rules.maxQuality}p limit`
    if (!rules.allowed.has('mp4') && !rules.allowed.has('mkv')) return 'video is not allowed'
    return null
}

/** Make a choice fit the rules: allowed formats, the quality limit and the fixed codec. */
export function fitRules(choice: QuickChoice, options: QuickDownloadOptions, rules: QuickRules): QuickChoice {
    let next = {...choice}
    if (!rules.allowed.has(next.container)) next.container = next.container === 'mp4' ? 'mkv' : 'mp4'
    if (!rules.allowed.has(next.audioFormat)) next.audioFormat = next.audioFormat === 'm4a' ? 'mp3' : 'm4a'
    if (options.formatChoices && rules.fixedCodec) next.codec = rules.fixedCodec
    if (options.formatChoices || options.qualityChoices) {
        if (rules.maxQuality != null && (next.quality == null || next.quality > rules.maxQuality)) {
            const capped = options.videos.map((v) => v.quality ?? null).filter((q): q is number => q != null && q <= rules.maxQuality!)
            next.quality = (next.quality == null ? null : capped[0] ?? null) as QuickQuality | null
        }
    }
    if (next.kind === 'video' && qualityBlocked(next.quality, rules) === 'video is not allowed') next = {...next, kind: 'audio'}
    return next
}

/** What keeps the current choice from starting under the rules, as the page shows it. */
export function ruleProblem(options: QuickDownloadOptions, choice: QuickChoice, rules: QuickRules): string | null {
    if (rules.allowedSources && !rules.allowedSources.includes(options.link.source.id)) {
        return `Quick download from ${options.link.source.name} is turned off in Settings.`
    }
    const format = choice.kind === 'audio' ? choice.audioFormat : choice.container
    if (!rules.allowed.has(format)) return `${format.toUpperCase()} is not allowed by the rules in Settings.`
    if (choice.kind === 'video' && options.formatChoices && rules.fixedCodec) {
        const video = videoOption(options, choice.quality)
        if (video && !video.codecs.some((c) => c.codec === rules.fixedCodec)) {
            return `This quality is not offered in ${CODEC_NAMES[rules.fixedCodec]}, which the rules in Settings require.`
        }
    }
    const size = choiceSize(options, choice)
    if (rules.maxBytes && size && size > rules.maxBytes) {
        return `This file would be about ${formatBytes(size)}. The rules allow up to ${formatBytes(rules.maxBytes)}. Pick a lower quality or Audio.`
    }
    if (rules.maxDurationSeconds && options.duration && options.duration > rules.maxDurationSeconds) {
        return `This video is ${Math.round(options.duration / 60)} minutes long. The rules allow up to ${Math.round(rules.maxDurationSeconds / 60)} minutes.`
    }
    return null
}
