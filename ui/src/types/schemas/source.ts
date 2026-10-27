import {z} from "zod";

/** Optional capabilities of a Source, as the backend names them. */
export const SourceFeature = {
    SHOWS: 'shows',
    MOVIES: 'movies',
    MOVIE_EXTRAS: 'movie_extras',
    BROWSE: 'browse',
    LOGIN: 'login',
    LIVE_EPISODES: 'live_episodes',
    MEMBERSHIP_LEVELS: 'membership_levels',
    RSS_STREAMING: 'rss_streaming',
    VIDEOS: 'videos',
    EPISODE_LISTS: 'episode_lists',
    SEARCH: 'search',
    COSTLY_SEARCH: 'costly_search',
    PROGRAM_UPDATES: 'program_updates',
    COOKIES: 'cookies',
    API_KEY: 'api_key',
    QUICK_CHECK: 'quick_check',
    CATALOGUE_REFRESH: 'catalogue_refresh',
} as const
export type SourceFeatureValue = typeof SourceFeature[keyof typeof SourceFeature]

/** The Daily Wire, whose catalog and show endpoints the UI calls by name. */
export const DAILYWIRE_SOURCE_KEY = 'dailywire'

/** Fields every item from a Source carries. */
export const SourcedFields = {
    sourceKey: z.string(),
    sourceFeatures: z.array(z.string()),
}

export function hasSourceFeature(
    item: {sourceFeatures?: readonly string[] | null} | null | undefined,
    feature: SourceFeatureValue,
): boolean {
    return !!item?.sourceFeatures?.includes(feature)
}

export const SourceReadSchema = z.object({
    id: z.string(),
    name: z.string(),
    domains: z.array(z.string()),
    features: z.array(z.string()),
    searchLabel: z.string().nullable().optional(),
})
export type SourceRead = z.infer<typeof SourceReadSchema>

export function sourceHas(source: SourceRead | null | undefined, feature: SourceFeatureValue): boolean {
    return !!source?.features.includes(feature)
}

export const ResolvedLinkReadSchema = z.object({
    source: SourceReadSchema,
    kind: z.enum(['show', 'movie', 'episode', 'video']),
    slug: z.string(),
    url: z.string(),
    showSlug: z.string().nullable(),
    showUrl: z.string().nullable(),
    site: z.string().nullable(),
    drmProtected: z.boolean(),
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
    kind: z.enum(['show', 'movie', 'episode', 'video']),
    slug: z.string(),
    url: z.string(),
    title: z.string(),
    description: z.string().nullable(),
    imageUrl: z.string().nullable(),
    authorName: z.string().nullable(),
    showSlug: z.string().nullable(),
    showUrl: z.string().nullable(),
    kindLabel: z.string().nullable().optional(),
    facts: z.array(z.string()).optional(),
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

export const SourceDomainReadSchema = z.object({
    domain: z.string(),
    sourceKeys: z.array(z.string()),
    defaultSourceKey: z.string(),
    preferredSourceKey: z.string().nullable(),
})
export type SourceDomainRead = z.infer<typeof SourceDomainReadSchema>

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
    selectedByDefault: z.boolean(),
    rssEpisodeType: z.enum(['full', 'trailer', 'bonus']),
    /** Episodes with the main tag follow the show's numbering. */
    main: z.boolean(),
})
export type EpisodeTagRead = z.infer<typeof EpisodeTagReadSchema>

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
    /** The shows the key speeds up, and what one full re-scan of them costs. */
    showCount: z.number(),
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

export const CookiesReadSchema = z.object({hasCookies: z.boolean()})
export type CookiesRead = z.infer<typeof CookiesReadSchema>

/** A show at a Source with listed episodes, shaped like the fields of a new show. */
export const ShowDetailsReadSchema = z.object({
    sourceKey: z.string(),
    slug: z.string(),
    title: z.string(),
    description: z.string().nullable(),
    sharingUrl: z.string(),
    authorName: z.string(),
    authorSlug: z.string(),
    thumbnailLandscapePath: z.string().nullable(),
    /** The show's own seasons, oldest first; empty when VODLoft makes a season per upload year. */
    seasons: z.array(z.object({slug: z.string(), name: z.string()})),
})
export type ShowDetailsRead = z.infer<typeof ShowDetailsReadSchema>
