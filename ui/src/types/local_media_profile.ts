import {createSelectRegistry, SelectRegistry} from "../utils/selectRegistry";
import {useMemo} from "react";
import type {LocalMediaProfileRead} from "./schemas/local_media_profile";
import type {LocalMediaProfileSiteRead, LocalMediaProfileSitesRead, LocalMediaProfileSubtitleMode} from "./schemas/local_media_profile_base";
import type {DownloadOptions} from "./schemas/source";


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

/** Every Site whose media a Local Media Profile of this type can store. */
export function sitesForLocalMediaProfileType(
    sites: LocalMediaProfileSitesRead | undefined,
    type: LocalMediaProfileType,
): LocalMediaProfileSiteRead[] {
    return (sites?.sites ?? []).filter((site) => site.profileTypes.includes(type))
}

/** The profile's Sites that offer something, and whether Sites still to come do too. */
export function profileSitesOffering(
    sites: LocalMediaProfileSitesRead | undefined,
    type: LocalMediaProfileType,
    siteKeys: readonly string[] | null | undefined,
    includeUpcomingSites: boolean | undefined,
    offers: (options: DownloadOptions) => boolean,
): {sites: LocalMediaProfileSiteRead[], upcoming: boolean} {
    return {
        sites: sitesForLocalMediaProfileType(sites, type)
            .filter((site) => (siteKeys == null || siteKeys.includes(site.key)) && offers(site.downloadOptions)),
        upcoming: !!sites && (siteKeys == null || !!includeUpcomingSites) && takesUpcomingSites(sites, type)
            && offers(sites.upcomingDownloadOptions),
    }
}

/** The profile's Sites that have a setting only some Sites show, such as sponsorblock, and whether Sites still to
 * come have it. */
export function profileSitesWithSetting(
    sites: LocalMediaProfileSitesRead | undefined,
    type: LocalMediaProfileType,
    siteKeys: readonly string[] | null | undefined,
    includeUpcomingSites: boolean | undefined,
    setting: string,
): {sites: LocalMediaProfileSiteRead[], upcoming: boolean} {
    return {
        sites: sitesForLocalMediaProfileType(sites, type)
            .filter((site) => (siteKeys == null || siteKeys.includes(site.key)) && site.settings.includes(setting)),
        upcoming: !!sites && (siteKeys == null || !!includeUpcomingSites) && takesUpcomingSites(sites, type)
            && sites.upcomingSettings.includes(setting),
    }
}

/** Names the Sites, as in "NPO Start, YouTube and upcoming sites". */
export function siteNames({sites, upcoming}: {sites: readonly {name: string}[], upcoming: boolean}): string {
    const names = [...sites.map((site) => site.name), ...(upcoming ? ['upcoming sites'] : [])]
    return names.length > 1 ? `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}` : (names[0] ?? '')
}

/** Whether a profile of this type can get media from Sites VODLoft has not seen yet. */
export function takesUpcomingSites(sites: LocalMediaProfileSitesRead | undefined, type: LocalMediaProfileType): boolean {
    return !!sites?.upcomingProfileTypes.includes(type)
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
        hlsHeights: [...new Set(options.flatMap((option) => option.hlsHeights))].sort((a, b) => a - b),
        subtitles: options.some((option) => option.subtitles),
        qualityChoices: options.some((option) => option.qualityChoices),
    }
}

/** What a profile can download: everything one of the Sites it is offered for can. */
export function profileDownloadOptions(
    sites: LocalMediaProfileSitesRead | undefined,
    type: LocalMediaProfileType,
    siteKeys: readonly string[] | null | undefined,
    includeUpcomingSites: boolean | undefined,
): DownloadOptions | undefined {
    if (!sites) return undefined
    const offered = sitesForLocalMediaProfileType(sites, type)
        .filter((site) => siteKeys == null || siteKeys.includes(site.key))
        .map((site) => site.downloadOptions)
    if ((siteKeys == null || includeUpcomingSites) && takesUpcomingSites(sites, type)) offered.push(sites.upcomingDownloadOptions)
    return combinedDownloadOptions(offered)
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

/**
 * Whether a profile is offered for media from a Site. A Site VODLoft has not seen yet is offered every profile
 * that includes upcoming Sites; media whose Site is not known yet is offered every profile.
 */
export function isLocalMediaProfileAvailableForSite(
    profile: Pick<LocalMediaProfileRead, 'siteKeys' | 'includeUpcomingSites'>,
    siteKey: string | null | undefined,
    knownSiteKeys?: readonly string[],
): boolean {
    if (!siteKey || profile.siteKeys.includes(siteKey)) return true
    return profile.includeUpcomingSites && !!knownSiteKeys && !knownSiteKeys.includes(siteKey)
}

/** Build a select registry for Local Media Profiles from an array (no memoization). */
export function buildLocalMediaProfileSelectRegistry(
    mediaProfiles: readonly LocalMediaProfileRead[] | undefined | null,
    type?: LocalMediaProfileType,
    collectionType?: CollectionLocalMediaProfileContext,
    siteKey?: string | null,
): SelectRegistry{
    const spec: Record<string, { label: string }> = {}
    const values: string[] = []
    if (Array.isArray(mediaProfiles)) {
        for (const p of mediaProfiles) {
            if (type && p.type !== type) continue
            if (type === 'collection' && collectionType && !isCollectionLocalMediaProfileAvailableFor(p, collectionType)) continue
            if (!isLocalMediaProfileAvailableForSite(p, siteKey)) continue
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
    siteKey?: string | null,
): SelectRegistry{
    return useMemo(
        (): SelectRegistry => buildLocalMediaProfileSelectRegistry(mediaProfiles, type, collectionType, siteKey),
        [mediaProfiles, type, collectionType, siteKey],
    )
}
