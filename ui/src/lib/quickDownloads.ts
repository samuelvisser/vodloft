import {useQuery} from '@tanstack/react-query'
import {
    MP3_BITRATES,
    QUICK_QUALITIES,
    QuickAudioOption,
    QuickChoice,
    QuickCodec,
    QuickDownloadAcceptedSchema,
    QuickDownloadOptions,
    QuickDownloadOptionsSchema,
    QuickDownloadsSchema,
    QuickQuality,
    QuickVideoOption,
    Mp3Bitrate,
} from '../types/schemas/quick_download'
import type {QuickDownloadSettings} from '../types/schemas/settings'
import {formatBytes} from '../utils/formatting'

export const QUICK_DOWNLOAD_OPERATION_KIND = 'quick.download'
export const quickDownloadsQueryKey = ['quickDownloads'] as const

export const CODEC_NAMES: Record<QuickCodec, string> = {h264: 'H.264', h265: 'H.265', vp9: 'VP9', av1: 'AV1'}
export const CODEC_NOTES: Record<QuickCodec, string> = {
    h264: 'plays everywhere',
    h265: 'smaller, newer devices',
    vp9: 'smaller, newer devices',
    av1: 'smallest, newest devices',
}

function apiBase(): string {
    return ((window as any).appConfig?.API_URL || '/api').replace(/\/+$/, '')
}

async function responseError(response: Response): Promise<Error> {
    let detail = `HTTP ${response.status}`
    try {
        const body = await response.json()
        if (typeof body?.detail === 'string') detail = body.detail
    } catch {
        // Keep the status text when the body is not JSON.
    }
    return new Error(detail)
}

/** Look a link up, with what it can be quick downloaded as. */
export async function fetchQuickDownloadOptions(url: string, signal?: AbortSignal, sourceKey?: string): Promise<QuickDownloadOptions> {
    const response = await fetch(`${apiBase()}/quick-downloads/options`, {
        method: 'POST',
        credentials: 'include',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(sourceKey ? {url, sourceKey} : {url}),
        signal,
    })
    if (!response.ok) throw await responseError(response)
    return QuickDownloadOptionsSchema.parse(await response.json())
}

export async function startQuickDownload(url: string, sourceKey: string, choice: QuickChoice) {
    const response = await fetch(`${apiBase()}/quick-downloads`, {
        method: 'POST',
        credentials: 'include',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({url, sourceKey, choice}),
    })
    if (!response.ok) throw await responseError(response)
    return QuickDownloadAcceptedSchema.parse(await response.json())
}

export async function removeQuickDownload(quickId: string): Promise<void> {
    const response = await fetch(`${apiBase()}/quick-downloads/${encodeURIComponent(quickId)}`, {
        method: 'DELETE',
        credentials: 'include',
    })
    if (!response.ok && response.status !== 404) throw await responseError(response)
}

export function quickDownloadFileUrl(quickId: string): string {
    return `${apiBase()}/quick-downloads/${encodeURIComponent(quickId)}/file`
}

export function useQuickDownloads() {
    return useQuery({
        queryKey: quickDownloadsQueryKey,
        queryFn: async ({signal}) => {
            const response = await fetch(`${apiBase()}/quick-downloads`, {signal, credentials: 'include'})
            if (!response.ok) throw await responseError(response)
            return QuickDownloadsSchema.parse(await response.json())
        },
        // Ready files count down to their deletion, and a finished download marks them delivered.
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
        return {...choice, quality: null, container: 'mp4', codec: null, audioFormat: 'm4a', audioBitrate: null}
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
