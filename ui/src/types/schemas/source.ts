import {z} from "zod";
import {ApiDateTimeSchema} from "./datetime";

/** A word as the backend names it: one, many, and one with its article, such as album, albums and an album. */
export const NamesSchema = z.object({singular: z.string(), plural: z.string(), a: z.string()})
export type Names = z.infer<typeof NamesSchema>

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
    PROGRAM_UPDATES: 'program_updates',
    COOKIES: 'cookies',
    OPTIONAL_COOKIES: 'optional_cookies',
    API_KEY: 'api_key',
    QUICK_CHECK: 'quick_check',
    CATALOGUE_REFRESH: 'catalogue_refresh',
    YTDLP_OPTIONS: 'ytdlp_options',
    METADATA_REFRESH: 'metadata_refresh',
    EPISODE_LOOKUPS: 'episode_lookups',
    PAGE_STREAMS: 'page_streams',
    OWN_STUDIO: 'own_studio',
    CREATORS: 'creators',
    CHAPTERS: 'chapters',
    LINK_COLLECTIONS: 'link_collections',
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
    /** VODLoft has the access the media needs, such as through the account it signs in with. */
    accessGranted: z.boolean().optional().default(false),
    /** What the Site calls the access, such as Members only or NPO Plus. */
    accessLabel: z.string().nullable().optional().default(null),
    /** One sentence from the Site on who can watch it, such as "Only NPO Plus subscribers can watch this." */
    accessDescription: z.string().nullable().optional().default(null),
}

/** Media on a Site that removes its media itself after a while, such as Twitch its past broadcasts. */
export const RetentionFields = {
    ...LockableFields,
    /** The Site removed the media itself, so it is gone for good there and VODLoft did not ask about it on Home. */
    removedByRetention: z.boolean().optional().default(false),
    /** The Site that removed it, and how that Site removes its media. */
    removedBy: z.object({siteName: z.string(), retention: z.string()}).nullable().optional().default(null),
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
    /** The resolutions of the Site's HLS bundle; none when it has no bundle. */
    hlsHeights: z.array(z.number().int()),
    /** The Site's media has subtitles a profile can save. */
    subtitles: z.boolean(),
    /** Codecs, container, quality goal, audio format and audio language pick the version that is downloaded. */
    qualityChoices: z.boolean(),
    /** The Site's downloader writes an info file about each video, which a profile can save. */
    infoFile: z.boolean(),
})
export type DownloadOptions = z.infer<typeof DownloadOptionsSchema>

/** A Site a Source finds things on by name. A costly search, such as one that uses API quota, runs when asked
 *  instead of while the user types. */
export const SearchSiteReadSchema = z.object({
    key: z.string(),
    name: z.string(),
    costlySearch: z.boolean(),
    /** The Site is added to VODLoft, so Add Media offers its search. */
    added: z.boolean(),
    /** The Source can search the Site now: one whose search goes through its own API once that is set up. */
    ready: z.boolean().default(true),
})
export type SearchSiteRead = z.infer<typeof SearchSiteReadSchema>

export const SourceReadSchema = z.object({
    id: z.string(),
    name: z.string(),
    domains: z.array(z.string()),
    features: z.array(z.string()),
    /** What the Source downloads from, when its name does not say so, such as YouTube, and many more. */
    sitesLabel: z.string().nullable().optional(),
    /** The Sites the Source can search by name, such as YouTube and SoundCloud for yt-dlp, each searched on its own. */
    searchSites: z.array(SearchSiteReadSchema).default([]),
    /** The Sites the Source is made for, such as The Daily Wire, and whether each is added to VODLoft, so Add Media
     *  offers to browse its catalogue. */
    sites: z.array(z.object({key: z.string(), name: z.string(), added: z.boolean()})).default([]),
    /** What the Source calls each kind of media, such as show for a Daily Wire collection, or VODLoft's word. */
    kindNames: z.record(z.string(), NamesSchema),
    /** The Sites the Source is made for, such as The Daily Wire; none for a Source of many sites. */
    siteKeys: z.array(z.string()).default([]),
    /** Which moment the Source's release dates mark: when an item came out or began (Released), or when it was
     *  finished and put up, such as after a livestream ended (Published). */
    releaseDate: z.enum(['start', 'end']),
    /** What a Local Media Profile can download for media of this Source: what any of its Sites offers. */
    downloadOptions: DownloadOptionsSchema,
})
export type SourceRead = z.infer<typeof SourceReadSchema>

export function sourceHas(source: SourceRead | null | undefined, feature: SourceFeatureValue): boolean {
    return !!source?.features.includes(feature)
}

/** Whether VODLoft shows the Source: one made for some Sites, such as The Daily Wire, only while one of them is
 *  added to VODLoft; a Source of many sites always. */
export function sourceShown(source: SourceRead): boolean {
    return !source.sites.length || source.sites.some((site) => site.added)
}

/** The links of a description that are on a Site VODLoft knows for media. */
export const MediaLinksReadSchema = z.object({urls: z.array(z.string())})

/** What a link shows: its title, description, picture and maker. A lookup may send one early from a quicker look. */
export const LinkPreviewReadSchema = z.object({
    title: z.string(),
    description: z.string().nullable(),
    imageUrl: z.string().nullable(),
    authorName: z.string().nullable(),
})
export type LinkPreviewRead = z.infer<typeof LinkPreviewReadSchema>

export const ResolvedLinkReadSchema = z.object({
    source: SourceReadSchema,
    /** A creator link, such as a Daily Wire host's page, can't be added: add one of their shows instead. */
    kind: z.enum(['collection', 'movie', 'episode', 'video', 'creator']),
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
    preview: LinkPreviewReadSchema,
    /** For a collection: whether it is a channel or one list. */
    collectionKind: z.enum(['channel', 'list']).nullable().optional().default(null),
    /** For a collection on a Site with creators, which can be in one: what its Site calls the creator behind it, such
     *  as host on The Daily Wire. */
    creatorNames: NamesSchema.nullable().optional().default(null),
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

/** What the Source calls a kind of media, such as show for a Daily Wire collection; none until the Source is known. */
export function kindNames(source: SourceRead | null | undefined, kind: string): Names | undefined {
    return source?.kindNames[kind]
}

/** The website a collection or video is on, such as YouTube, whichever Source fetches it. */
/** One type of section a Site's creators have, such as a feed, or an album or a playlist on SoundCloud, and what the
 * Site calls it. */
export const SectionTypeSchema = z.object({
    key: z.string(),
    kind: z.enum(['feed', 'list', 'show', 'item']),
    names: NamesSchema,
})
export type SectionType = z.infer<typeof SectionTypeSchema>

export const SiteReadSchema = z.object({
    key: z.string(),
    name: z.string(),
    /** The Site's Font Awesome icon as prefix:name, such as fab:youtube; see SiteIcon. */
    icon: z.string().nullable().optional(),
    /** The Site's name in at most two letters, such as YT, shown beside a globe where it has no icon. */
    initials: z.string(),
    /** A collection on the Site shows what VODLoft has no access to until the user hides it. */
    showsLocked: z.boolean().optional().default(true),
    /** The Site has sound only, such as Bandcamp: a Music collection on it holds tracks, not music videos. */
    audioOnly: z.boolean().optional().default(false),
    /** What the Site calls one of its videos: a video, or a track on a Site with sound only. */
    mediaNames: NamesSchema,
    /** What the Site calls a creator, in lower case, such as host on The Daily Wire. */
    creatorNames: NamesSchema,
    /** Every type of section the Site's creators have, such as YouTube's feeds and playlists. */
    sectionTypes: z.array(SectionTypeSchema),
    /** What the Site calls its lists, all its types of list together, such as albums and playlists. */
    sectionListNames: NamesSchema,
    /** What the Site calls a collection of a channel's uploads, such as a YouTube channel. */
    channelCollectionNames: NamesSchema,
    /** What the Site calls a collection of one list, such as a YouTube playlist. */
    listCollectionNames: NamesSchema,
    /** A channel's playlists or albums at the Site can be seasons of its collection. */
    linkSeasons: z.boolean().default(false),
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
    names: NamesSchema,
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

/** A Site whose API key would speed up collections or creators in the Library, while there is none. */
export const ApiKeyNoteReadSchema = z.object({
    sourceKey: z.string(),
    siteName: z.string(),
})
export type ApiKeyNoteRead = z.infer<typeof ApiKeyNoteReadSchema>

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
    /** What one quick check of each of those collections costs, and how long it waits between checks anyway. */
    checkCosts: z.array(z.object({units: z.number(), leastMinutes: z.number(), feeds: z.number()})),
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

/** A Site's own free API that the user can register VODLoft with, such as Twitch's. */
export const SiteApiReadSchema = z.object({
    name: z.string(),
    fields: z.array(z.object({key: z.string(), label: z.string(), secret: z.boolean()})),
    benefits: z.string(),
    steps: z.array(z.object({text: z.string(), button: z.string().nullable(), url: z.string().nullable()})),
    /** The Site's search goes through the API, so Add Media only searches it once it is set up. */
    searches: z.boolean(),
})
export type SiteApiRead = z.infer<typeof SiteApiReadSchema>

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
    /** The Site's own API, on a Site that has one a Source uses. */
    siteApi: SiteApiReadSchema.nullable().default(null),
    /** Which values of the Site's API are set, a secret by its last few characters, and the last problem with them. */
    siteApiStatus: z.object({
        hints: z.record(z.string(), z.string()),
        problem: z.string().nullable(),
        setUp: z.boolean(),
    }).nullable().default(null),
    /** The user can remove the Site: VODLoft has nothing from it and no Source is made for it. */
    removable: z.boolean(),
})
export type SiteAuthenticationRead = z.infer<typeof SiteAuthenticationReadSchema>

/** A Site added by a link to it. */
export const SiteAddedReadSchema = z.object({key: z.string(), name: z.string()})
export type SiteAddedRead = z.infer<typeof SiteAddedReadSchema>

/** A Site the user can pick as one they use: a popular one VODLoft suggests, or one already added. */
export const SiteChoiceReadSchema = z.object({
    key: z.string(),
    name: z.string(),
    /** What VODLoft adds from the Site, in a few words. */
    pitch: z.string().nullable(),
    /** VODLoft knows the Site already. */
    added: z.boolean(),
    icon: z.string().nullable(),
    initials: z.string(),
})
export type SiteChoiceRead = z.infer<typeof SiteChoiceReadSchema>


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
    /** Why the collection was taken for music, when it was, such as an album on YouTube Music. */
    musicReason: z.string().nullable().optional(),
    /** The collection's own seasons, oldest first; empty when VODLoft makes a season per upload year. */
    seasons: z.array(z.object({slug: z.string(), name: z.string()})),
    /** The collection's Site has sound only, such as SoundCloud: a Music collection there holds tracks. */
    audioOnly: z.boolean().default(false),
    /** What the link is: a channel, or one list, such as a playlist or an album, which is the collection's one season. */
    kind: z.enum(['channel', 'list']),
    /** Which of its Site's types of list the link is, such as an album or a playlist on SoundCloud, where its link doesn't tell. */
    listType: z.string().nullable().default(null),
    /** What the collection's seasons will be once added, by collection type, as its Site's defaults make them. */
    seasonsPlans: z.record(z.string(), z.string()).default({}),
})
export type CollectionDetailsRead = z.infer<typeof CollectionDetailsReadSchema>

/** The yt-dlp options a Source gives every download. */
export const YtdlpOptionsReadSchema = z.object({text: z.string()})
