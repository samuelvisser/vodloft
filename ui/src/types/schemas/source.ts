import {z} from "zod";
import {ApiDateTimeSchema} from "./datetime";

/** Optional capabilities of a Source, as the backend names them. */
export const SourceFeature = {
    COLLECTIONS: 'collections',
    MOVIES: 'movies',
    MOVIE_EXTRAS: 'movie_extras',
    BROWSE: 'browse',
    LOGIN: 'login',
    LIVE_EPISODES: 'live_episodes',
    MEMBERSHIP_LEVELS: 'membership_levels',
    VIDEOS: 'videos',
    EPISODE_LISTS: 'episode_lists',
    SEARCH: 'search',
    COSTLY_SEARCH: 'costly_search',
    PROGRAM_UPDATES: 'program_updates',
    COOKIES: 'cookies',
    OPTIONAL_COOKIES: 'optional_cookies',
    API_KEY: 'api_key',
    QUICK_CHECK: 'quick_check',
    CATALOGUE_REFRESH: 'catalogue_refresh',
    YTDLP_OPTIONS: 'ytdlp_options',
    EPISODE_LOOKUPS: 'episode_lookups',
    PAGE_STREAMS: 'page_streams',
    OWN_STUDIO: 'own_studio',
} as const
export type SourceFeatureValue = typeof SourceFeature[keyof typeof SourceFeature]

/** The domain a Source names when it works with any site. */
export const ANY_DOMAIN = '*'

/** The Daily Wire, whose catalog and show endpoints the UI calls by name. */
export const DAILYWIRE_SOURCE_KEY = 'dailywire'

/** Fields every item from a Source carries. */
export const SourcedFields = {
    sourceKey: z.string(),
    sourceFeatures: z.array(z.string()),
}

/** Media that may need an access, such as a channel membership; accessLabel is what its Site calls it. */
export const LockableFields = {
    access: z.string().nullable().optional().default(null),
    accessRefusedAt: ApiDateTimeSchema.nullable().optional().default(null),
    /** When VODLoft next checks whether the locked media opened up. */
    accessCheckAt: ApiDateTimeSchema.nullable().optional().default(null),
    /** VODLoft cannot download the media without the access, so it does not try. */
    accessLocked: z.boolean().optional().default(false),
    /** What the Site calls the access, such as Members only or NPO Plus. */
    accessLabel: z.string().nullable().optional().default(null),
    /** One sentence from the Site on who can watch it, such as "Only NPO Plus subscribers can watch this." */
    accessDescription: z.string().nullable().optional().default(null),
}


export function hasSourceFeature(
    item: {sourceFeatures?: readonly string[] | null} | null | undefined,
    feature: SourceFeatureValue,
): boolean {
    return !!item?.sourceFeatures?.includes(feature)
}

/** What a Local Media Profile can download for a Site, or for any Site of a Source. */
export const DownloadOptionsSchema = z.object({
    /** The resolutions worth downloading up to. */
    videoHeights: z.array(z.number().int()),
    audioOnly: z.boolean(),
    /** The Site's HLS stream with every resolution in it, as The Daily Wire offers. */
    hlsBundle: z.boolean(),
    /** Codecs, container, quality goal, audio format and audio language pick the version that is downloaded. */
    qualityChoices: z.boolean(),
})
export type DownloadOptions = z.infer<typeof DownloadOptionsSchema>

export const SourceReadSchema = z.object({
    id: z.string(),
    name: z.string(),
    domains: z.array(z.string()),
    features: z.array(z.string()),
    /** What the Source downloads from, when its name does not say so, such as YouTube, and many more. */
    sitesLabel: z.string().nullable().optional(),
    searchLabel: z.string().nullable().optional(),
    /** What the Source calls a kind of media in its own catalogue, such as Show for a Daily Wire collection. */
    kindNames: z.record(z.string(), z.string()).optional(),
    /** What a Local Media Profile can download for media of this Source: what any of its Sites offers. */
    downloadOptions: DownloadOptionsSchema,
})
export type SourceRead = z.infer<typeof SourceReadSchema>

export function sourceHas(source: SourceRead | null | undefined, feature: SourceFeatureValue): boolean {
    return !!source?.features.includes(feature)
}

export const ResolvedLinkReadSchema = z.object({
    source: SourceReadSchema,
    kind: z.enum(['collection', 'movie', 'episode', 'video']),
    slug: z.string(),
    url: z.string(),
    collectionSlug: z.string().nullable(),
    collectionUrl: z.string().nullable(),
    site: z.string().nullable(),
    drmProtected: z.boolean(),
    access: z.string().nullable().optional().default(null),
    accessLabel: z.string().nullable().optional().default(null),
    accessDescription: z.string().nullable().optional().default(null),
    accessLocked: z.boolean().optional().default(false),
    preview: z.object({
        title: z.string(),
        description: z.string().nullable(),
        imageUrl: z.string().nullable(),
        authorName: z.string().nullable(),
    }),
    /** Every Source that claims the link's site, preferred first. */
    candidates: z.array(SourceReadSchema),
})
export type ResolvedLinkRead = z.infer<typeof ResolvedLinkReadSchema>

export const SearchResultReadSchema = z.object({
    kind: z.enum(['collection', 'movie', 'episode', 'video']),
    slug: z.string(),
    url: z.string(),
    title: z.string(),
    description: z.string().nullable(),
    imageUrl: z.string().nullable(),
    authorName: z.string().nullable(),
    collectionSlug: z.string().nullable(),
    collectionUrl: z.string().nullable(),
    kindLabel: z.string().nullable().optional(),
    facts: z.array(z.string()).optional(),
    access: z.string().nullable().optional(),
    accessLabel: z.string().nullable().optional(),
})
export type SearchResultRead = z.infer<typeof SearchResultReadSchema>

export const SearchNoticeReadSchema = z.object({
    badge: z.string(),
    text: z.string(),
    tone: z.enum(['neutral', 'warning']),
    linkLabel: z.string().nullable(),
    linkPath: z.string().nullable(),
})
export type SearchNoticeRead = z.infer<typeof SearchNoticeReadSchema>

export const SearchResultsReadSchema = z.object({
    results: z.array(SearchResultReadSchema),
    notice: SearchNoticeReadSchema.nullable(),
})
export type SearchResultsRead = z.infer<typeof SearchResultsReadSchema>

/** What a search button names: the Source's own label, such as YouTube for yt-dlp, or its name. */
export function searchName(source: SourceRead | null | undefined): string | undefined {
    return source?.searchLabel ?? source?.name
}

/** What the Source calls a kind of media where it shows its own catalogue, or VODLoft's word for it. */
export function kindName(source: SourceRead | null | undefined, kind: string, vodloftName: string): string {
    return source?.kindNames?.[kind] ?? vodloftName
}

/** The plural of a kind name, such as Shows for Show; Series stays Series. */
export function pluralKindName(name: string): string {
    return name.endsWith('s') ? name : `${name}s`
}

/** The website a collection or video is on, such as YouTube, whichever Source fetches it. */
export const SiteReadSchema = z.object({
    key: z.string(),
    name: z.string(),
})
export type SiteRead = z.infer<typeof SiteReadSchema>

export const SourceSiteReadSchema = z.object({
    key: z.string(),
    name: z.string(),
    domains: z.array(z.string()),
    sourceKeys: z.array(z.string()),
    defaultSourceKey: z.string(),
    preferredSourceKey: z.string().nullable(),
})
export type SourceSiteRead = z.infer<typeof SourceSiteReadSchema>

export const ProgramStatusReadSchema = z.object({
    name: z.string(),
    version: z.string().nullable(),
    lastUpdateAt: z.string().nullable(),
    lastUpdateError: z.string().nullable(),
})
export type ProgramStatusRead = z.infer<typeof ProgramStatusReadSchema>

/** A kind of episode a Source tells apart, such as a YouTube Short; profiles select tags by key. */
export const EpisodeTagReadSchema = z.object({
    key: z.string(),
    label: z.string(),
    help: z.string(),
    /** Names a count of these episodes, such as "1 livestream" or "726 livestreams". */
    singular: z.string(),
    plural: z.string(),
    selectedByDefault: z.boolean(),
    rssEpisodeType: z.enum(['full', 'trailer', 'bonus']),
    /** Episodes with the main tag follow the collection's numbering. */
    main: z.boolean(),
})
export type EpisodeTagRead = z.infer<typeof EpisodeTagReadSchema>

/** What a Source calls one publish status, such as The Daily Wire's "Published (still contains countdown)". */
export const PublishStatusLabelReadSchema = z.object({
    status: z.string(),
    label: z.string(),
    help: z.string(),
})
export type PublishStatusLabelRead = z.infer<typeof PublishStatusLabelReadSchema>

export function episodeTagLabel(tags: readonly EpisodeTagRead[] | undefined, key: string): string {
    return tags?.find((tag) => tag.key === key)?.label ?? key
}

export const ApiStatusReadSchema = z.object({
    /** The last characters of the key, or null when no key is set. */
    keyHint: z.string().nullable(),
    shares: z.array(z.object({name: z.string(), used: z.number(), limit: z.number()})),
    dailyQuota: z.number(),
    /** The service said today's quota is used up. */
    exhausted: z.boolean(),
    resetsAt: z.string(),
    problem: z.string().nullable(),
    problemFixUrl: z.string().nullable(),
    /** The collections the key speeds up, and what one full re-scan of them costs. */
    collectionCount: z.number(),
    rescanUnits: z.number(),
})
export type ApiStatusRead = z.infer<typeof ApiStatusReadSchema>

export const SourceProblemReadSchema = z.object({
    sourceKey: z.string(),
    sourceName: z.string(),
    title: z.string(),
    detail: z.string(),
    fixUrl: z.string().nullable(),
})
export type SourceProblemRead = z.infer<typeof SourceProblemReadSchema>

export const SiteAuthenticationReadSchema = z.object({
    key: z.string(),
    name: z.string(),
    domains: z.array(z.string()),
    /** The Source made for the Site with a sign-in of its own, such as The Daily Wire's. */
    signInSourceKey: z.string().nullable(),
    /** The Sources that sign in on the Site with its cookies file. */
    cookieSourceNames: z.array(z.string()),
    /** How to export a cookies file for the Site, when it needs more than the usual. */
    cookiesHelp: z.string().nullable(),
    hasCookies: z.boolean(),
    cookieCount: z.number(),
    /** What the cookies file signs in as, for a Site whose Source can tell. */
    cookiesStatus: z.object({label: z.string(), ok: z.boolean(), detail: z.string().nullable()}).nullable(),
    /** The Source whose API key is for the Site, such as yt-dlp's YouTube Data API key. */
    apiKeySourceKey: z.string().nullable(),
})
export type SiteAuthenticationRead = z.infer<typeof SiteAuthenticationReadSchema>

/** A Site added by a link to it. */
export const SiteAddedReadSchema = z.object({key: z.string(), name: z.string()})
export type SiteAddedRead = z.infer<typeof SiteAddedReadSchema>


/** A collection at a Source with listed episodes, shaped like the fields of a new collection. */
export const CollectionDetailsReadSchema = z.object({
    sourceKey: z.string(),
    slug: z.string(),
    title: z.string(),
    description: z.string().nullable(),
    sharingUrl: z.string(),
    authorName: z.string(),
    authorSlug: z.string(),
    thumbnailLandscapePath: z.string().nullable(),
    /** The type VODLoft suggests from the collection's name. */
    probableCollectionType: z.string(),
    /** The collection's own seasons, oldest first; empty when VODLoft makes a season per upload year. */
    seasons: z.array(z.object({slug: z.string(), name: z.string()})),
})
export type CollectionDetailsRead = z.infer<typeof CollectionDetailsReadSchema>

/** The yt-dlp options a Source gives every download. */
export const YtdlpOptionsReadSchema = z.object({text: z.string()})
