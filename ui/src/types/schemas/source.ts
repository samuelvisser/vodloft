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
    PROGRAM_UPDATES: 'program_updates',
    COOKIES: 'cookies',
} as const
export type SourceFeatureValue = typeof SourceFeature[keyof typeof SourceFeature]

export const DEFAULT_SOURCE_KEY = 'dailywire'

/** Fields every item from a Source carries. */
export const SourcedFields = {
    sourceKey: z.string().default(DEFAULT_SOURCE_KEY),
    sourceFeatures: z.array(z.string()).default([]),
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
    showSlug: z.string().nullable().optional(),
    showUrl: z.string().nullable().optional(),
    site: z.string().nullable().optional(),
    drmProtected: z.boolean().optional().default(false),
    preview: z.object({
        title: z.string(),
        description: z.string().nullable().optional(),
        imageUrl: z.string().nullable().optional(),
        authorName: z.string().nullable().optional(),
    }),
    /** Every Source that claims the link's site, preferred first. */
    candidates: z.array(SourceReadSchema).optional().default([]),
})
export type ResolvedLinkRead = z.infer<typeof ResolvedLinkReadSchema>

export const SearchResultReadSchema = z.object({
    kind: z.enum(['show', 'movie', 'episode', 'video']),
    slug: z.string(),
    url: z.string(),
    title: z.string(),
    description: z.string().nullable().optional(),
    imageUrl: z.string().nullable().optional(),
    authorName: z.string().nullable().optional(),
    showSlug: z.string().nullable().optional(),
    showUrl: z.string().nullable().optional(),
})
export type SearchResultRead = z.infer<typeof SearchResultReadSchema>

export const SourceDomainReadSchema = z.object({
    domain: z.string(),
    sourceKeys: z.array(z.string()),
    defaultSourceKey: z.string(),
    preferredSourceKey: z.string().nullable().optional(),
})
export type SourceDomainRead = z.infer<typeof SourceDomainReadSchema>

export const ProgramStatusReadSchema = z.object({
    name: z.string(),
    version: z.string().nullable().optional(),
    lastUpdateAt: z.string().nullable().optional(),
    lastUpdateError: z.string().nullable().optional(),
})
export type ProgramStatusRead = z.infer<typeof ProgramStatusReadSchema>

export const CookiesReadSchema = z.object({hasCookies: z.boolean()})
export type CookiesRead = z.infer<typeof CookiesReadSchema>

/** A show at a Source with listed episodes, shaped like the fields of a new show. */
export const ShowDetailsReadSchema = z.object({
    sourceKey: z.string(),
    slug: z.string(),
    title: z.string(),
    description: z.string().nullable().optional(),
    sharingUrl: z.string(),
    authorName: z.string(),
    authorSlug: z.string(),
    thumbnailLandscapePath: z.string().nullable().optional(),
})
export type ShowDetailsRead = z.infer<typeof ShowDetailsReadSchema>
