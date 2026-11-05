import {createSelectRegistry, SelectRegistry} from "../utils/selectRegistry";
import {useMemo} from "react";
import type {LocalMediaProfileRead} from "./schemas/local_media_profile";
import type {LocalMediaProfileSubtitleMode} from "./schemas/local_media_profile_base";
import {type DownloadOptions, SourceFeature, type SourceFeatureValue, type SourceRead, sourceHas} from "./schemas/source";


export const PreferredFormatReg = createSelectRegistry("PreferredFormat", {
  'format_360p': { label: "360p", help: "Up to 360p" },
  'format_480p': { label: "480p", help: "Up to 480p" },
  'format_720p':   { label: "720p",   help: "Download a 720p video" },
  'format_1080p':   { label: "1080p",   help: "Download an 1080p video" },
  'format_1440p': { label: "1440p", help: "Up to 1440p" },
  'format_4k':   { label: "4K",   help: "Download a 4k video" },
  'format_8k': { label: "8K", help: "Up to 8K" },
  'format_hls': { label: "HLS (up to 1080p)", help: "Download an adaptive HLS video package with every resolution up to 1080p" },
  'format_audio_only':   { label: "Audio Only",   help: "Download audio only" },
});

export const MoviePreferredFormatReg = createSelectRegistry("MoviePreferredFormat", {
  'format_4k': { label: "4k", help: "Download a 4k video" },
  'format_1080p': { label: "1080p", help: "Download a 1080p video" },
  'format_720p': { label: "720p", help: "Download a 720p video" },
  'format_480p': { label: "480p", help: "Download a 480p video" },
});

export const VideoPreferredFormatReg = createSelectRegistry("VideoPreferredFormat", {
  'format_360p': { label: "360p" },
  'format_480p': { label: "480p" },
  'format_720p': { label: "720p" },
  'format_1080p': { label: "1080p" },
  'format_1440p': { label: "1440p" },
  'format_4k': { label: "4K" },
  'format_8k': { label: "8K" },
  'format_audio_only': { label: "Audio Only", help: "Download audio only" },
});

export const LocalMediaProfileTypeReg = createSelectRegistry("LocalMediaProfileType", {
  'collection': { label: "Collection", help: "Store downloaded collection episodes" },
  'movie': { label: "Movie", help: "Store manually downloaded movies" },
  'video': { label: "Video", help: "Store single videos added on their own" },
});

export const CollectionLocalMediaProfileScopeReg = createSelectRegistry("CollectionLocalMediaProfileScope", {
  'both': { label: "Podcasts and Series", help: "Offer this profile for both Podcasts and Series" },
  'podcast': { label: "Podcasts", help: "Offer this profile only for Podcasts" },
  'series': { label: "Series", help: "Offer this profile only for Series" },
});

export type LocalMediaProfileType = 'collection' | 'movie' | 'video'
/** The API collection that creates, updates and deletes profiles of one type. */
export function localMediaProfileEndpoint(type: LocalMediaProfileType | string): string {
    return `${type}-local-media-profiles`
}

export type CollectionLocalMediaProfileScope = (typeof CollectionLocalMediaProfileScopeReg)["values"][number]
export type CollectionLocalMediaProfileContext = 'podcast' | 'series'

export function defaultSubtitleModeForProfile(
    type: LocalMediaProfileType,
    collectionScope: CollectionLocalMediaProfileScope = 'both',
): LocalMediaProfileSubtitleMode {
    // New Video profiles start without subtitles; they can be turned on like any other profile.
    if (type === 'video') return 'no_subtitles'
    return type === 'collection' && collectionScope === 'podcast' ? 'no_subtitles' : 'sidecar'
}

export function isCollectionLocalMediaProfileAvailableFor(
    profile: LocalMediaProfileRead,
    collectionType: string | null | undefined,
): boolean {
    if (profile.type !== 'collection') return false
    if (collectionType !== 'podcast' && collectionType !== 'series') return true
    const scope = profile.collectionScope ?? 'both'
    return scope === 'both' || scope === collectionType
}

/** The Feature a Source needs before a profile of this type can store its media. */
const PROFILE_TYPE_SOURCE_FEATURES: Record<LocalMediaProfileType, SourceFeatureValue> = {
    collection: SourceFeature.COLLECTIONS,
    movie: SourceFeature.MOVIES,
    video: SourceFeature.VIDEOS,
}

/** Every Source whose media a Local Media Profile of this type can store. */
export function sourcesForLocalMediaProfileType(
    sources: readonly SourceRead[] | undefined,
    type: LocalMediaProfileType,
): SourceRead[] {
    return (sources ?? []).filter((source) => sourceHas(source, PROFILE_TYPE_SOURCE_FEATURES[type]))
}

/** The resolution each video format downloads up to. */
export const FORMAT_HEIGHTS: Record<string, number> = {
    format_360p: 360, format_480p: 480, format_720p: 720, format_1080p: 1080,
    format_1440p: 1440, format_4k: 2160, format_8k: 4320,
}

/** Everything that at least one of these offers. */
export function combinedDownloadOptions(options: readonly DownloadOptions[]): DownloadOptions {
    return {
        videoHeights: [...new Set(options.flatMap((option) => option.videoHeights))].sort((a, b) => a - b),
        audioOnly: options.some((option) => option.audioOnly),
        hlsBundle: options.some((option) => option.hlsBundle),
        qualityChoices: options.some((option) => option.qualityChoices),
    }
}

/** What a profile can download: everything one of the Sources it is offered for can. */
export function profileDownloadOptions(
    sources: readonly SourceRead[] | undefined,
    type: LocalMediaProfileType,
    sourceKeys: readonly string[] | null | undefined,
): DownloadOptions | undefined {
    if (!sources) return undefined
    const offered = sourcesForLocalMediaProfileType(sources, type)
        .filter((source) => sourceKeys == null || sourceKeys.includes(source.id))
    return combinedDownloadOptions(offered.map((source) => source.downloadOptions))
}

export function offersFormat(options: DownloadOptions, format: string): boolean {
    if (format === 'format_hls') return options.hlsBundle
    if (format === 'format_audio_only') return options.audioOnly
    return options.videoHeights.includes(FORMAT_HEIGHTS[format])
}

/** The offered video format nearest to this one: the highest below it, or the lowest there is. */
export function nearestVideoFormat(options: DownloadOptions, format: string): string | undefined {
    const wanted = format === 'format_hls' || format === 'format_audio_only' ? 1080 : FORMAT_HEIGHTS[format]
    const fitting = options.videoHeights.filter((height) => height <= wanted)
    const height = fitting.length ? Math.max(...fitting) : Math.min(...options.videoHeights)
    return Object.keys(FORMAT_HEIGHTS).find((key) => FORMAT_HEIGHTS[key] === height)
}

/** A profile without a list of Sources is offered for every Source. */
export function isLocalMediaProfileAvailableForSource(
    profile: Pick<LocalMediaProfileRead, 'sourceKeys'>,
    sourceKey: string | null | undefined,
): boolean {
    return !sourceKey || profile.sourceKeys == null || profile.sourceKeys.includes(sourceKey)
}

/** Build a select registry for Local Media Profiles from an array (no memoization). */
export function buildLocalMediaProfileSelectRegistry(
    mediaProfiles: readonly LocalMediaProfileRead[] | undefined | null,
    type?: LocalMediaProfileType,
    collectionType?: CollectionLocalMediaProfileContext,
    sourceKey?: string | null,
): SelectRegistry{
    const spec: Record<string, { label: string }> = {}
    const values: string[] = []
    if (Array.isArray(mediaProfiles)) {
        for (const p of mediaProfiles) {
            if (type && p.type !== type) continue
            if (type === 'collection' && collectionType && !isCollectionLocalMediaProfileAvailableFor(p, collectionType)) continue
            if (!isLocalMediaProfileAvailableForSource(p, sourceKey)) continue
            const id = (p as any).id
            const name = (p as any).name ?? String(id)
            if (typeof id === 'number') {
                const value = String(id)
                spec[value] = {label: String(name)}
                values.push(value)
            }
        }
    }
    return createSelectRegistry('LocalMediaProfile', spec, values)
}

/** React hook: memoized select registry for Local Media Profiles */
export function useLocalMediaProfileSelectRegistry(
    mediaProfiles: readonly LocalMediaProfileRead[] | undefined | null,
    type?: LocalMediaProfileType,
    collectionType?: CollectionLocalMediaProfileContext,
    sourceKey?: string | null,
): SelectRegistry{
    return useMemo(
        (): SelectRegistry => buildLocalMediaProfileSelectRegistry(mediaProfiles, type, collectionType, sourceKey),
        [mediaProfiles, type, collectionType, sourceKey],
    )
}
