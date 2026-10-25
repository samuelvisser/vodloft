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
    preview: z.object({
        title: z.string(),
        description: z.string().nullable().optional(),
        imageUrl: z.string().nullable().optional(),
        authorName: z.string().nullable().optional(),
    }),
})
export type ResolvedLinkRead = z.infer<typeof ResolvedLinkReadSchema>

export const ProgramStatusReadSchema = z.object({
    name: z.string(),
    version: z.string().nullable().optional(),
    lastUpdateAt: z.string().nullable().optional(),
    lastUpdateError: z.string().nullable().optional(),
})
export type ProgramStatusRead = z.infer<typeof ProgramStatusReadSchema>

export const CookiesReadSchema = z.object({hasCookies: z.boolean()})
export type CookiesRead = z.infer<typeof CookiesReadSchema>
