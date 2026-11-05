import {presentDownloadProgress} from './downloadProgress'
import {can, type Area} from './access'
import {
    type InfiniteData,
    keepPreviousData,
    QueryClient,
    useInfiniteQuery,
    useQuery,
    useQueryClient,
} from '@tanstack/react-query'
import {useEffect, useMemo, useRef} from 'react'
import {saveEpisodePreviewToStorage, saveProfilesToStorage, saveCollectionsToStorage} from './cache'
import {
    type LazyCollectionPage,
    type LazyCollectionPageRequest,
    contiguousLazyCollectionItems,
    lazyCollectionQueryKey,
    updateLazyCollectionEntities,
    useLazyCollection,
} from './lazyCollection'
import {useFrontendPuller} from './puller'
import {SiteRefreshReadSchema, type SiteRefreshFormValues, type SiteRefreshRead} from '../types/schemas/siteRefresh'
import {downloadStatusesForApi} from './downloadStatusFilters'
import {
    episodeQueryKeys,
    fetchEpisodePage,
    seasonsQueryOptions,
    COLLECTION_EPISODE_PREVIEW_SIZE,
    collectionQueryOptions,
    collectionsQueryOptions,
} from './collectionQueryOptions'
import {
    LocalMediaProfileRead,
    LocalMediaProfileReadSchema,
    LocalMediaProfileViewRead,
    LocalMediaProfileViewReadSchema,
} from "../types/schemas/local_media_profile";
import {AutoSubtitlesUseSchema, DownloadProfileRead, DownloadProfileReadSchema, SiteOptionsSchema, SkippedByFilterSchema} from "../types/schemas/download_profile";
import {DownloadProfileReadView, DownloadProfileReadViewSchema} from "../types/schemas/download_profile_view";
import {StreamProfileRead, StreamProfileReadSchema, StreamProfileReadView, StreamProfileReadViewSchema} from "../types/schemas/stream_profile_base";
import {CollectionRead, CollectionReadView, CollectionReadViewSchema} from "../types/schemas/collection";
import {
    EpisodeIndexedActivityRead,
    EpisodeIndexedActivityReadSchema,
    EpisodeRead,
    EpisodeReadSchema,
    EpisodeReadView,
    EpisodeReadViewPage,
} from "../types/schemas/episode";
import {RssStreamProfileRead, RssStreamProfileReadSchema} from "../types/schemas/rss_stream_profile";
import {DailywireUserInfoRead, DailywireUserInfoReadSchema} from "../types/schemas/dailywire_user_info";
import {DailywireShowRead} from "../types/schemas/dailywire_show";
import {
    MediaDownloadDomainViewRead,
    MediaDownloadPageReadSchema,
    MediaDownloadViewRead,
    MediaDownloadViewReadSchema,
} from "../types/schemas/media_download";
import {TaskOperationRead} from "../types/schemas/operation";
import {MovieRead, MovieReadSchema} from "../types/schemas/movie";
import {VideoRead, VideoReadSchema} from "../types/schemas/video";
import {
    ApiStatusRead, ApiStatusReadSchema, CookiesRead, EpisodeTagRead, EpisodeTagReadSchema, PublishStatusLabelRead, PublishStatusLabelReadSchema, CookiesReadSchema, ProgramStatusRead, SourceProblemRead,
    SourceProblemReadSchema, ProgramStatusReadSchema, ResolvedLinkRead,
    ResolvedLinkReadSchema, SearchResultsRead, SearchResultsReadSchema, CollectionDetailsRead, CollectionDetailsReadSchema, SourceSiteRead, SourceSiteReadSchema, SourceRead,
    SourceReadSchema,
    YtdlpOptionsReadSchema,
} from "../types/schemas/source";
import {
    DailywireCatalogRead,
    DailywireCatalogReadSchema,
    DailywireCatalogMoviePageReadSchema,
    DailywireCatalogShowPageReadSchema,
    DailywireMovieRead,
    DailywireMovieReadSchema,
} from "../types/schemas/dailywire_catalog";

async function fetchJSON<T>(url: string, signal?: AbortSignal): Promise<T> {
    const r = await fetch(url, {signal, credentials: 'include'})
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    return r.json() as Promise<T>
}

async function fetchParsed<T>(
    url: string,
    schema: {parse(value: unknown): T},
    signal?: AbortSignal,
): Promise<T> {
    return schema.parse(await fetchJSON<unknown>(url, signal))
}

/** Profile lists are also read by the Add pages and by library managers picking a profile. */
function profileListsReadable(area: Area): boolean {
    return can(area) || can('add_media') || can('library', 'manage')
}

export function useLocalMediaProfiles() {
    const result = useQuery<LocalMediaProfileRead[], Error, LocalMediaProfileRead[], readonly ['localMediaProfiles']>({
        queryKey: ['localMediaProfiles'] as const,
        enabled: profileListsReadable('local_media_profiles'),
        queryFn: ({signal}) => fetchParsed(
            `${(window as any).appConfig.API_URL}/local-media-profiles`,
            LocalMediaProfileReadSchema.array(),
            signal,
        ),
        refetchOnMount: 'always',
    })
    useEffect(() => {
        if (result.data) saveProfilesToStorage(result.data)
    }, [result.data])
    return result
}

export function useLocalMediaProfilesView() {
    return useQuery<LocalMediaProfileViewRead[], Error, LocalMediaProfileViewRead[], readonly ['localMediaProfilesView']>({
        queryKey: ['localMediaProfilesView'] as const,
        enabled: profileListsReadable('local_media_profiles'),
        queryFn: ({signal}) => fetchParsed(
            `${(window as any).appConfig.API_URL}/local-media-profiles/as-view`,
            LocalMediaProfileViewReadSchema.array(),
            signal,
        ),
        refetchOnMount: 'always',
    })
}

export function useLocalMediaProfileView(slug?: string) {
    return useQuery<LocalMediaProfileViewRead, Error, LocalMediaProfileViewRead, readonly ['localMediaProfileView', string | undefined]>({
        queryKey: ['localMediaProfileView', slug] as const,
        enabled: !!slug,
        queryFn: ({signal}) => fetchParsed(
            `${(window as any).appConfig.API_URL}/local-media-profiles/${encodeURIComponent(slug!)}/view`,
            LocalMediaProfileViewReadSchema,
            signal,
        ),
        refetchOnMount: 'always',
    })
}

export function useDownloadProfilesView() {
    return useQuery<DownloadProfileReadView[], Error, DownloadProfileReadView[], readonly ['downloadProfilesView']>({
        queryKey: ['downloadProfilesView'] as const,
        enabled: profileListsReadable('download_profiles'),
        queryFn: ({signal}) => fetchParsed(
            `${(window as any).appConfig.API_URL}/download-profiles/as-view`,
            DownloadProfileReadViewSchema.array(),
            signal,
        ),
        refetchOnMount: 'always',
    })
}

export function useRssStreamProfiles() {
    return useQuery<RssStreamProfileRead[], Error, RssStreamProfileRead[], readonly ['rssStreamProfiles']>({
        queryKey: ['rssStreamProfiles'] as const,
        enabled: can('stream_profiles') || can('library', 'manage'),
        queryFn: ({signal}) => fetchParsed(
            `${(window as any).appConfig.API_URL}/rss-stream-profiles`,
            RssStreamProfileReadSchema.array(),
            signal,
        ),
        refetchOnMount: 'always',
    })
}

export function useStreamProfilesView() {
    return useQuery<StreamProfileReadView[], Error, StreamProfileReadView[], readonly ['streamProfilesView']>({
        queryKey: ['streamProfilesView'] as const,
        enabled: can('stream_profiles') || can('library', 'manage'),
        queryFn: ({signal}) => fetchParsed(
            `${(window as any).appConfig.API_URL}/stream-profiles/as-view`,
            StreamProfileReadViewSchema.array(),
            signal,
        ),
        refetchOnMount: 'always',
    })
}

export function useCollections() {
    const result = useQuery({...collectionsQueryOptions(), enabled: can('library')})
    useEffect(() => {
        if (result.data) saveCollectionsToStorage(result.data)
    }, [result.data])
    return result
}

export function useCollectionsView() {
    return useQuery<CollectionReadView[], Error, CollectionReadView[], readonly ['collectionsView']>({
        queryKey: ['collectionsView'] as const,
        enabled: can('library'),
        queryFn: ({signal}) => fetchParsed(
            `${(window as any).appConfig.API_URL}/collections/as-view`,
            CollectionReadViewSchema.array(),
            signal,
        ),
        refetchOnMount: 'always',
    })
}

export function useMovies() {
    return useQuery<MovieRead[], Error, MovieRead[], readonly ['movies']>({
        queryKey: ['movies'] as const,
        enabled: can('library'),
        queryFn: ({signal}) => fetchParsed(
            `${(window as any).appConfig.API_URL}/movies`,
            MovieReadSchema.array(),
            signal,
        ),
        refetchOnMount: 'always',
    })
}

export function useVideos() {
    return useQuery<VideoRead[], Error, VideoRead[], readonly ['videos']>({
        queryKey: ['videos'] as const,
        enabled: can('library'),
        queryFn: ({signal}) => fetchParsed(
            `${(window as any).appConfig.API_URL}/videos`,
            VideoReadSchema.array(),
            signal,
        ),
        refetchOnMount: 'always',
    })
}

export function useVideo(id?: number) {
    return useQuery<VideoRead, Error, VideoRead, readonly ['video', number | undefined]>({
        queryKey: ['video', id] as const,
        enabled: id !== undefined && Number.isFinite(id),
        queryFn: ({signal}) => fetchParsed(
            `${(window as any).appConfig.API_URL}/videos/${id}`,
            VideoReadSchema,
            signal,
        ),
        refetchOnMount: 'always',
    })
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

/** Add a single video by its link, at the Source that recognised the link. */
export async function addVideo(url: string, sourceKey: string): Promise<VideoRead> {
    const response = await fetch(`${(window as any).appConfig.API_URL}/videos`, {
        method: 'POST',
        credentials: 'include',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({url, sourceKey}),
    })
    if (!response.ok) throw await responseError(response)
    return VideoReadSchema.parse(await response.json())
}

export function useSources() {
    return useQuery<SourceRead[], Error, SourceRead[], readonly ['sources']>({
        queryKey: ['sources'] as const,
        queryFn: ({signal}) => fetchParsed(
            `${(window as any).appConfig.API_URL}/sources`,
            SourceReadSchema.array(),
            signal,
        ),
        staleTime: Infinity,
    })
}

/** The Sources by id, with a name fallback for items whose Source is no longer registered. */
export function useSourceLookup() {
    const {data: sources} = useSources()
    return useMemo(() => {
        const byId = new Map((sources ?? []).map((source) => [source.id, source]))
        return {
            sources: sources ?? [],
            get: (id?: string | null) => (id ? byId.get(id) : undefined),
            name: (id?: string | null) => (id ? byId.get(id)?.name ?? id : ''),
        }
    }, [sources])
}

export function useSourceProgram(sourceId: string, enabled = true) {
    return useQuery<ProgramStatusRead, Error, ProgramStatusRead, readonly ['sourceProgram', string]>({
        queryKey: ['sourceProgram', sourceId] as const,
        enabled,
        queryFn: ({signal}) => fetchParsed(
            `${(window as any).appConfig.API_URL}/sources/${encodeURIComponent(sourceId)}/program`,
            ProgramStatusReadSchema,
            signal,
        ),
    })
}

/** Fetch the latest version of the program a Source runs. */
export async function updateSourceProgram(sourceId: string): Promise<ProgramStatusRead> {
    const response = await fetch(`${(window as any).appConfig.API_URL}/sources/${encodeURIComponent(sourceId)}/program/update`, {
        method: 'POST',
        credentials: 'include',
    })
    if (!response.ok) throw await responseError(response)
    return ProgramStatusReadSchema.parse(await response.json())
}

export function useSourceCookies(sourceId: string, enabled = true) {
    return useQuery<CookiesRead, Error, CookiesRead, readonly ['sourceCookies', string]>({
        queryKey: ['sourceCookies', sourceId] as const,
        enabled,
        queryFn: ({signal}) => fetchParsed(
            `${(window as any).appConfig.API_URL}/sources/${encodeURIComponent(sourceId)}/cookies`,
            CookiesReadSchema,
            signal,
        ),
    })
}


/** The yt-dlp options a Source gives every download. */
export function useSourceYtdlpOptions(sourceId: string) {
    return useQuery<string, Error, string, readonly ['sourceYtdlpOptions', string]>({
        queryKey: ['sourceYtdlpOptions', sourceId] as const,
        queryFn: async ({signal}) => (await fetchParsed(
            `${(window as any).appConfig.API_URL}/sources/${encodeURIComponent(sourceId)}/ytdlp-options`,
            YtdlpOptionsReadSchema,
            signal,
        )).text,
    })
}

/** Store the yt-dlp options a Source gives every download. A refused line comes back as the error. */
export async function saveSourceYtdlpOptions(sourceId: string, text: string): Promise<string> {
    const response = await fetch(`${(window as any).appConfig.API_URL}/sources/${encodeURIComponent(sourceId)}/ytdlp-options`, {
        method: 'PUT',
        credentials: 'include',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({text}),
    })
    if (response.status === 422) {
        const body = await response.json().catch(() => null)
        const problem = (body?.detail ?? [])[0]
        throw new Error(problem?.msg ? String(problem.msg).replace(/^Value error, /, '') : 'These options could not be saved')
    }
    if (!response.ok) throw await responseError(response)
    return YtdlpOptionsReadSchema.parse(await response.json()).text
}

/** Store a cookies.txt file for a Source, or remove it with null. */
export async function saveSourceCookies(sourceId: string, content: string | null): Promise<CookiesRead> {
    const response = await fetch(`${(window as any).appConfig.API_URL}/sources/${encodeURIComponent(sourceId)}/cookies`, {
        method: content === null ? 'DELETE' : 'PUT',
        credentials: 'include',
        headers: content === null ? undefined : {'Content-Type': 'application/json'},
        body: content === null ? undefined : JSON.stringify({content}),
    })
    if (!response.ok) throw await responseError(response)
    return CookiesReadSchema.parse(await response.json())
}

/** The tags a Source gives episodes of the show at ``url``, or of any of its shows without one. */
export function useEpisodeTags(sourceKey?: string | null, url?: string | null) {
    return useQuery<EpisodeTagRead[], Error, EpisodeTagRead[], readonly ['episodeTags', string, string | null]>({
        queryKey: ['episodeTags', sourceKey ?? '', url ?? null] as const,
        enabled: !!sourceKey,
        staleTime: Infinity,
        queryFn: ({signal}) => fetchParsed(
            `${(window as any).appConfig.API_URL}/sources/${encodeURIComponent(sourceKey ?? '')}/episode-tags`
            + (url ? `?url=${encodeURIComponent(url)}` : ''),
            EpisodeTagReadSchema.array(),
            signal,
        ),
    })
}

/** What a Source calls each publish status, by status. */
export function usePublishStatusLabels(sourceKey?: string | null) {
    return useQuery<PublishStatusLabelRead[], Error, Record<string, PublishStatusLabelRead>, readonly ['publishStatusLabels', string]>({
        queryKey: ['publishStatusLabels', sourceKey ?? ''] as const,
        enabled: !!sourceKey,
        staleTime: Infinity,
        queryFn: ({signal}) => fetchParsed(
            `${(window as any).appConfig.API_URL}/sources/${encodeURIComponent(sourceKey ?? '')}/publish-statuses`,
            PublishStatusLabelReadSchema.array(),
            signal,
        ),
        select: (labels) => Object.fromEntries(labels.map((label) => [label.status, label])),
    })
}

/** The episode tags of a saved show, or of a show about to be added from ``sourceKey`` at ``url``. */
export function useCollectionEpisodeTags({collectionId, collectionSlug, sourceKey, url}: {
    collectionId?: number, collectionSlug?: string, sourceKey?: string, url?: string,
}) {
    const {data: collections} = useCollections()
    const collection = collectionId !== undefined
        ? collections?.find((item) => item.id === collectionId)
        : collectionSlug ? collections?.find((item) => item.slug === collectionSlug) : undefined
    return useEpisodeTags(collection?.sourceKey ?? sourceKey, collection?.sharingUrl ?? url)
}

export function useSourceApi(sourceId: string, enabled = true) {
    return useQuery<ApiStatusRead, Error, ApiStatusRead, readonly ['sourceApi', string]>({
        queryKey: ['sourceApi', sourceId] as const,
        enabled,
        queryFn: ({signal}) => fetchParsed(
            `${(window as any).appConfig.API_URL}/sources/${encodeURIComponent(sourceId)}/api`,
            ApiStatusReadSchema,
            signal,
        ),
        refetchInterval: 60_000,
    })
}

/** The service did not accept an API key; ``fixUrl`` is where the user can fix it. */
export class ApiKeyRejectedError extends Error {
    constructor(message: string, readonly fixUrl: string | null) {
        super(message)
    }
}

/** Save and test a new key ('save'), test the stored one ('test') or remove it ('remove'). */
export async function changeSourceApiKey(
    sourceId: string, action: 'save' | 'test' | 'remove', key?: string,
): Promise<ApiStatusRead> {
    const base = `${(window as any).appConfig.API_URL}/sources/${encodeURIComponent(sourceId)}/api/key`
    const response = await fetch(action === 'test' ? `${base}/test` : base, {
        method: {save: 'PUT', test: 'POST', remove: 'DELETE'}[action],
        credentials: 'include',
        headers: action === 'save' ? {'Content-Type': 'application/json'} : undefined,
        body: action === 'save' ? JSON.stringify({key}) : undefined,
    })
    if (response.status === 422) {
        const body = await response.json().catch(() => null)
        const detail = body?.detail
        if (typeof detail?.message === 'string') throw new ApiKeyRejectedError(detail.message, detail.fixUrl ?? null)
    }
    if (!response.ok) throw await responseError(response)
    return ApiStatusReadSchema.parse(await response.json())
}

/** What the user should fix about any Source, for Needs attention on Home. */
export function useSourceProblems() {
    return useQuery<SourceProblemRead[], Error, SourceProblemRead[], readonly ['sourceProblems']>({
        queryKey: ['sourceProblems'] as const,
        enabled: can('sources', 'manage'),
        queryFn: ({signal}) => fetchParsed(
            `${(window as any).appConfig.API_URL}/sources/problems`,
            SourceProblemReadSchema.array(),
            signal,
        ),
        refetchInterval: 60_000,
    })
}

/** Every Site a Source is made for, and the Source VODLoft asks first for its links. */
export function useSourceSites() {
    return useQuery<SourceSiteRead[], Error, SourceSiteRead[], readonly ['sourceSites']>({
        queryKey: ['sourceSites'] as const,
        queryFn: async ({signal}) => {
            const value = await fetchJSON<unknown>(`${(window as any).appConfig.API_URL}/sources/sites`, signal)
            return SourceSiteReadSchema.array().parse(value)
        },
    })
}

/** The metadata refresh schedule of every Site VODLoft has seen. */
export function useSiteRefresh() {
    return useQuery<SiteRefreshRead[], Error, SiteRefreshRead[], readonly ['siteRefresh']>({
        queryKey: ['siteRefresh'] as const,
        queryFn: async ({signal}) => {
            const value = await fetchJSON<unknown>(`${(window as any).appConfig.API_URL}/settings/site-refresh`, signal)
            return SiteRefreshReadSchema.array().parse(value)
        },
    })
}

/** Choose the schedule a Site's items follow; the form reads the response for field errors. */
export function saveSiteRefresh(key: string, values: SiteRefreshFormValues): Promise<Response> {
    return fetch(`${(window as any).appConfig.API_URL}/settings/site-refresh/${encodeURIComponent(key)}`, {
        method: 'PUT',
        credentials: 'include',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            refreshMode: values.refreshMode,
            refreshIntervals: values.refreshIntervals.trim() || null,
            pendingChecks: values.pendingChecks,
        }),
    })
}

/** Choose the Source to ask first for a Site's links; ``null`` goes back to the default. */
export async function saveSourceSite(key: string, preferredSourceKey: string | null): Promise<SourceSiteRead> {
    const response = await fetch(`${(window as any).appConfig.API_URL}/sources/sites/${encodeURIComponent(key)}`, {
        method: 'PUT',
        credentials: 'include',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({preferredSourceKey}),
    })
    if (!response.ok) throw await responseError(response)
    return SourceSiteReadSchema.parse(await response.json())
}

/** Shows and videos at a Source whose name matches the query. */
export function useSourceSearch(sourceId: string | undefined, query: string) {
    return useQuery<SearchResultsRead, Error, SearchResultsRead, readonly ['sourceSearch', string | undefined, string]>({
        queryKey: ['sourceSearch', sourceId, query] as const,
        enabled: !!sourceId && !!query,
        queryFn: async ({signal}) => {
            const params = new URLSearchParams({q: query})
            const response = await fetch(
                `${(window as any).appConfig.API_URL}/sources/${encodeURIComponent(sourceId!)}/search?${params}`,
                {signal, credentials: 'include'},
            )
            if (!response.ok) throw await responseError(response)
            return SearchResultsReadSchema.parse(await response.json())
        },
        staleTime: 5 * 60 * 1000,
        retry: false,
    })
}

/** Which Source recognises a link, for pages that need to know before anything is added. */
export function useResolvedLink(url: string | undefined) {
    return useQuery<ResolvedLinkRead, Error, ResolvedLinkRead, readonly ['resolvedLink', string | undefined]>({
        queryKey: ['resolvedLink', url] as const,
        enabled: !!url,
        queryFn: ({signal}) => resolveLink(url!, signal),
        staleTime: 5 * 60 * 1000,
        retry: false,
    })
}

/** A collection to add, at a Source that lists its episodes. */
export function useListedCollectionDetails(sourceId: string | undefined, url: string | undefined) {
    return useQuery<CollectionDetailsRead, Error, CollectionDetailsRead, readonly ['listedCollection', string | undefined, string | undefined]>({
        queryKey: ['listedCollection', sourceId, url] as const,
        enabled: !!sourceId && !!url,
        queryFn: async ({signal}) => {
            const params = new URLSearchParams({url: url!})
            const response = await fetch(
                `${(window as any).appConfig.API_URL}/sources/${encodeURIComponent(sourceId!)}/collection?${params}`,
                {signal, credentials: 'include'},
            )
            if (!response.ok) throw await responseError(response)
            return CollectionDetailsReadSchema.parse(await response.json())
        },
        staleTime: 5 * 60 * 1000,
        retry: false,
    })
}

/** Ask the backend which Source recognises a link, and what it points to. ``sourceKey`` asks only that Source. */
export async function resolveLink(url: string, signal?: AbortSignal, sourceKey?: string): Promise<ResolvedLinkRead> {
    const response = await fetch(`${(window as any).appConfig.API_URL}/resolve`, {
        method: 'POST',
        credentials: 'include',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(sourceKey ? {url, sourceKey} : {url}),
        signal,
    })
    if (!response.ok) throw await responseError(response)
    return ResolvedLinkReadSchema.parse(await response.json())
}

export function useDailywireCatalog() {
    return useQuery<any, Error, DailywireCatalogRead, readonly ['dailywireCatalog']>({
        queryKey: ['dailywireCatalog'] as const,
        queryFn: async ({signal}) => {
            const value = await fetchJSON<any>(`${(window as any).appConfig.API_URL}/dailywire/catalog`, signal)
            return DailywireCatalogReadSchema.parse(value)
        },
        staleTime: 5 * 60 * 1000,
        refetchOnMount: false,
    })
}

const DAILYWIRE_CATALOG_PAGE_SIZE = 24

export function useDailywireShowCatalog(search: string, grouping: 'host' | 'alphabetical', enabled = true) {
    return useInfiniteQuery({
        queryKey: ['dailywireCatalog', 'collections', search, grouping] as const,
        enabled,
        initialPageParam: 0,
        queryFn: async ({pageParam, signal}) => {
            const params = new URLSearchParams({
                offset: String(pageParam),
                limit: String(DAILYWIRE_CATALOG_PAGE_SIZE),
                grouping,
            })
            if (search) params.set('search', search)
            const value = await fetchJSON<any>(
                `${(window as any).appConfig.API_URL}/dailywire/catalog/shows?${params}`,
                signal,
            )
            return DailywireCatalogShowPageReadSchema.parse(value)
        },
        getNextPageParam: (lastPage) => lastPage.hasMore
            ? lastPage.offset + lastPage.items.length
            : undefined,
        staleTime: 5 * 60 * 1000,
        gcTime: 30 * 60 * 1000,
        refetchOnMount: false,
    })
}

export function useDailywireMovieCatalog(search: string, enabled = true) {
    return useInfiniteQuery({
        queryKey: ['dailywireCatalog', 'movies', search] as const,
        enabled,
        initialPageParam: 0,
        queryFn: async ({pageParam, signal}) => {
            const params = new URLSearchParams({
                offset: String(pageParam),
                limit: String(DAILYWIRE_CATALOG_PAGE_SIZE),
            })
            if (search) params.set('search', search)
            const value = await fetchJSON<any>(
                `${(window as any).appConfig.API_URL}/dailywire/catalog/movies?${params}`,
                signal,
            )
            return DailywireCatalogMoviePageReadSchema.parse(value)
        },
        getNextPageParam: (lastPage) => lastPage.hasMore
            ? lastPage.offset + lastPage.items.length
            : undefined,
        staleTime: 5 * 60 * 1000,
        gcTime: 30 * 60 * 1000,
        refetchOnMount: false,
    })
}

export function useDailywireMovie(slug?: string) {
    return useQuery<any, Error, DailywireMovieRead, readonly ['dailywireMovie', string | undefined]>({
        queryKey: ['dailywireMovie', slug] as const,
        enabled: !!slug,
        queryFn: async ({signal}) => {
            const value = await fetchJSON<any>(
                `${(window as any).appConfig.API_URL}/dailywire/movies/${encodeURIComponent(slug!)}`,
                signal,
            )
            return DailywireMovieReadSchema.parse(value)
        },
        staleTime: 5 * 60 * 1000,
    })
}

export function useCollection(id?: string) {
    const qc = useQueryClient()
    return useQuery({
        ...collectionQueryOptions(id, qc),
        enabled: !!id,
    })
}

export function useEpisodePages(
    collectionSlug?: string,
    opts?: {
        pageSize?: number
        seasonId?: number | null
        enabled?: boolean
    },
) {
    const pageSize = opts?.pageSize ?? 36
    const seasonId = opts?.seasonId
    const result = useLazyCollection<EpisodeReadView, EpisodeReadViewPage>({
        collectionPrefix: episodeQueryKeys.forCollection(collectionSlug),
        queryKey: ['pages', seasonId ?? null] as const,
        initialCount: pageSize,
        batchSize: pageSize,
        enabled: !!collectionSlug && seasonId !== null && (opts?.enabled ?? true),
        fetchPage: ({cursor, limit}, signal) => fetchEpisodePage(
            collectionSlug!,
            {
                cursor,
                limit,
                seasonId: seasonId ?? undefined,
            },
            signal,
        ),
    })

    const firstPage = result.data?.pages[0]
    useEffect(() => {
        if (!collectionSlug || seasonId !== undefined || firstPage === undefined) return
        saveEpisodePreviewToStorage(
            collectionSlug,
            firstPage.items.slice(0, COLLECTION_EPISODE_PREVIEW_SIZE),
            Date.now(),
            firstPage.collectionTotal,
        )
    }, [firstPage, seasonId, collectionSlug])

    return result
}

export function useEpisode(episodeId?: string) {
    return useQuery<EpisodeRead, Error, EpisodeRead, readonly ['episode', string | undefined]>({
        queryKey: ['episode', episodeId] as const,
        enabled: !!episodeId,
        queryFn: ({signal}) => fetchParsed(
            `${(window as any).appConfig.API_URL}/episodes/${episodeId}`,
            EpisodeReadSchema,
            signal,
        ),
    })
}

export function useRecentlyIndexedEpisodes(limit = 7) {
    return useQuery<
        EpisodeIndexedActivityRead[],
        Error,
        EpisodeIndexedActivityRead[],
        readonly ['recentlyIndexedEpisodes', number]
    >({
        queryKey: ['recentlyIndexedEpisodes', limit] as const,
        enabled: can('library'),
        queryFn: ({signal}) => fetchParsed(
            `${(window as any).appConfig.API_URL}/episodes/as-view/recently-indexed?limit=${limit}`,
            EpisodeIndexedActivityReadSchema.array(),
            signal,
        ),
        placeholderData: keepPreviousData,
        refetchOnMount: 'always',
    })
}

// Fetch DailyWire show preview by slug for Add Show URL step
export function useDailywireShow(slug?: string, membershipPlan?: string) {
    return useQuery<any, Error, DailywireShowRead, readonly ['dwCollection', string | undefined, string | undefined]>({
        queryKey: ['dwCollection', slug, membershipPlan] as const,
        enabled: !!slug,
        queryFn: async ({signal}) => {
            const urlBase = (window as any).appConfig.API_URL
            const params = membershipPlan ? `?membership_plan=${encodeURIComponent(membershipPlan)}` : ''
            const url = `${urlBase}/dailywire/shows/${encodeURIComponent(slug!)}` + params
            const r = await fetch(url, {signal, credentials: 'include'})
            if (!r.ok) {
                try {
                    const body = await r.json()
                    const detail = typeof body?.detail === 'string' ? body.detail : null
                    const err: any = new Error(detail || `HTTP ${r.status}`)
                    err.status = r.status
                    err.detail = detail
                    throw err
                } catch (_) {
                    const err: any = new Error(`HTTP ${r.status}`)
                    err.status = r.status
                    throw err
                }
            }
            return r.json()
        },
        retry: false,
    })
}

export function useDailywireUserInfo() {
    return useQuery<any, any & { status?: number }, DailywireUserInfoRead, readonly ['dwUserInfo']>({
        queryKey: ['dwUserInfo'] as const,
        queryFn: async ({signal}) => {
            const base = (window as any).appConfig?.API_URL?.replace(/\/+$/, '')
            const r = await fetch(`${base}/dailywire/user-info`, { signal, credentials: 'include' })
            if (!r.ok) {
                const err: any = new Error(`HTTP ${r.status}`)
                err.status = r.status
                try {
                    const body = await r.json()
                    if (typeof body?.detail === 'string') err.detail = body.detail
                } catch {}
                throw err
            }
            const j = await r.json()
            return DailywireUserInfoReadSchema.parse(j)
        },
        retry: false,
        refetchOnMount: 'always',
    })
}

export function useCollectionSeasons(collectionSlug?: string) {
    return useQuery({
        ...seasonsQueryOptions(collectionSlug),
        enabled: !!collectionSlug,
    })
}

/** Episodes of a Collection that its Download Profiles' own filters skip, with the filter. */
export function useSkippedByFilter(collectionId?: number) {
    return useQuery({
        queryKey: ['skippedByFilter', collectionId] as const,
        enabled: collectionId !== undefined,
        queryFn: ({signal}) => fetchParsed(
            `${(window as any).appConfig.API_URL}/download-profiles/skipped-by-filter/${collectionId}`,
            SkippedByFilterSchema.array(),
            signal,
        ),
    })
}

export function useAutoSubtitleUses(localMediaProfileId?: number) {
    return useQuery({
        queryKey: ['autoSubtitleUses', localMediaProfileId] as const,
        enabled: localMediaProfileId !== undefined,
        queryFn: ({signal}) => fetchParsed(
            `${(window as any).appConfig.API_URL}/download-profiles/auto-subtitles/${localMediaProfileId}`,
            AutoSubtitlesUseSchema.array(),
            signal,
        ),
    })
}

/** Choices only some sites offer, for a saved Collection or for the link of one that is being added. */
export function useSiteOptions({collectionId, sourceKey, url}: {collectionId?: number; sourceKey?: string; url?: string | null}) {
    return useQuery({
        queryKey: ['siteOptions', collectionId, sourceKey, url] as const,
        enabled: collectionId !== undefined || (!!sourceKey && !!url),
        queryFn: ({signal}) => fetchParsed(
            collectionId !== undefined
                ? `${(window as any).appConfig.API_URL}/download-profiles/site-options/${collectionId}`
                : `${(window as any).appConfig.API_URL}/sources/${encodeURIComponent(sourceKey ?? '')}/site-options?url=${encodeURIComponent(url ?? '')}`,
            SiteOptionsSchema,
            signal,
        ),
        staleTime: Infinity,
    })
}

export function useDownloadProfilesByCollectionSlug(collectionSlug?: string) {
    return useQuery<DownloadProfileRead[], Error, DownloadProfileRead[], readonly ['downloadProfilesByCollectionSlug', string | undefined]>({
        queryKey: ['downloadProfilesByCollectionSlug', collectionSlug] as const,
        enabled: !!collectionSlug,
        queryFn: ({signal}) => fetchParsed(
            `${(window as any).appConfig.API_URL}/download-profiles/by-collection-slug/${collectionSlug}`,
            DownloadProfileReadSchema.array(),
            signal,
        ),
        refetchOnMount: 'always',
    })
}

export function useStreamProfilesByCollectionSlug(collectionSlug?: string) {
    return useQuery<StreamProfileRead[], Error, StreamProfileRead[], readonly ['streamProfilesByCollectionSlug', string | undefined]>({
        queryKey: ['streamProfilesByCollectionSlug', collectionSlug] as const,
        enabled: !!collectionSlug,
        queryFn: ({signal}) => fetchParsed(
            `${(window as any).appConfig.API_URL}/stream-profiles/by-collection-slug/${collectionSlug}`,
            StreamProfileReadSchema.array(),
            signal,
        ),
        refetchOnMount: 'always',
    })
}

const ACTIVE_OPERATION_STATUSES = new Set(['QUEUED', 'RUNNING', 'WAITING'])

function contextString(operation: TaskOperationRead, key: string): string | null {
    const value = operation.context?.[key]
    return typeof value === 'string' ? value : null
}

function contextNumber(operation: TaskOperationRead, key: string): number | null {
    const value = operation.context?.[key]
    return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function contextBoolean(operation: TaskOperationRead, key: string): boolean | null {
    const value = operation.context?.[key]
    return typeof value === 'boolean' ? value : null
}

function progressMetaString(operation: TaskOperationRead | undefined, key: string): string | null {
    const value = operation?.progressMeta?.[key]
    return typeof value === 'string' ? value : null
}

function operationDate(value: string | null | undefined): Date | null {
    if (!value) return null
    const parsed = new Date(value)
    return Number.isNaN(parsed.getTime()) ? null : parsed
}

function operationForDownload(
    operations: TaskOperationRead[],
    mediaDownloadId: number,
): TaskOperationRead | undefined {
    return operations.filter((operation) => (
        operation.kind === 'media.download'
        && operation.resourceType === 'media_download'
        && operation.resourceId === mediaDownloadId
    )).sort((left, right) => Date.parse(right.createdAt || '') - Date.parse(left.createdAt || ''))[0]

}

function presentDownload(
    download: MediaDownloadDomainViewRead,
    operation?: TaskOperationRead,
): MediaDownloadViewRead {
    const presentation = presentDownloadProgress(download, operation)
    const status = presentation.status
    const operationError = operation?.status === 'FAILED'
        ? (operation.error || operation.message || null)
        : null
    return {
        ...download,
        formatDownloaded: progressMetaString(operation, 'selected_format') ?? download.formatDownloaded,
        downloadStatus: status,
        presentation,
        operation,
        errorMessage: operationError || download.artifactError || download.latestTaskError,
        startedAt: operationDate(operation?.startedAt) || download.latestTaskStartedAt,
        finishedAt: operationDate(operation?.finishedAt) || download.downloadedAt || download.latestTaskFinishedAt,
        isRedownloadAttempt: operation
            ? contextBoolean(operation, 'is_redownload')
            : download.latestTaskIsRedownload,
    }
}

function syntheticDownload(operation: TaskOperationRead): MediaDownloadDomainViewRead | null {
    if (
        operation.kind !== 'media.download'
        || operation.resourceType !== 'media_download'
        || operation.resourceId == null
        || !ACTIVE_OPERATION_STATUSES.has(operation.status)
    ) {
        return null
    }

    const mediaItemId = contextNumber(operation, 'media_item_id')
    const localMediaProfileId = contextNumber(operation, 'local_media_profile_id')
    const sourceKey = contextString(operation, 'source_key')
    if (mediaItemId == null || localMediaProfileId == null || sourceKey == null) return null

    const createdAt = operationDate(operation.createdAt) || new Date()
    return {
        id: operation.resourceId,
        sourceKey,
        sourceFeatures: [],
        type: contextString(operation, 'media_type') || 'episode',
        mediaItemId,
        localMediaProfileId,
        filePath: contextString(operation, 'file_path') || '',
        assets: [],
        artifactStatus: 'absent',
        artifactError: null,
        artifactSizeBytes: null,
        automaticRetrySuppressed: false,
        downloadedBytes: null,
        formatDownloaded: null,
        downloadedAt: null,
        firstSuccessfulDownloadAt: null,
        canDelete: true,
        createdAt,
        updatedAt: operationDate(operation.updatedAt) || createdAt,
        mediaSlug: contextString(operation, 'media_slug'),
        mediaTitle: contextString(operation, 'media_title'),
        episodeSlug: contextString(operation, 'episode_slug'),
        episodeTitle: contextString(operation, 'episode_title'),
        episodeIdentifier: contextString(operation, 'episode_identifier'),
        collectionSlug: contextString(operation, 'collection_slug'),
        collectionTitle: contextString(operation, 'collection_title'),
        movieSlug: contextString(operation, 'movie_slug'),
        movieTitle: contextString(operation, 'movie_title'),
        movieExtraType: contextString(operation, 'movie_extra_type'),
        localMediaProfileName: contextString(operation, 'local_media_profile_name'),
        preferredFormat: contextString(operation, 'preferred_format'),
        downloadedPublishStatus: null,
        latestTaskStatus: null,
        latestTaskError: null,
        latestTaskIsRedownload: null,
        latestTaskStartedAt: null,
        latestTaskFinishedAt: null,
    }
}

type MediaDownloadScope =
    | {kind: 'all'}
    | {kind: 'episode'; slug?: string}
    | {kind: 'movie'; slug?: string}
    | {kind: 'collection'; slug?: string}
    | {kind: 'video'; id?: number}

function mediaDownloadScopeKey(scope: MediaDownloadScope) {
    switch (scope.kind) {
        case 'episode':
            return ['episodeDownloads', scope.slug] as const
        case 'movie':
            return ['movieDownloads', scope.slug] as const
        case 'collection':
            return ['collectionDownloads', scope.slug] as const
        case 'video':
            return ['videoDownloads', scope.id] as const
        default:
            return ['mediaDownloadsView'] as const
    }
}

function mediaDownloadScopeUrl(scope: MediaDownloadScope) {
    const base = `${(window as any).appConfig.API_URL}/media-downloads/as-view`
    if (scope.kind === 'all') return base

    const params = new URLSearchParams()
    if (scope.kind === 'episode' && scope.slug) params.set('episode_slug', scope.slug)
    if (scope.kind === 'movie' && scope.slug) params.set('movie_slug', scope.slug)
    if (scope.kind === 'collection' && scope.slug) params.set('collection_slug', scope.slug)
    if (scope.kind === 'video' && scope.id !== undefined) params.set('video_id', String(scope.id))
    return `${base}?${params}`
}

function operationMatchesMediaDownloadScope(
    operation: TaskOperationRead,
    scope: MediaDownloadScope,
) {
    if (scope.kind === 'all') return true
    if (scope.kind === 'video') {
        return scope.id !== undefined
            && contextString(operation, 'media_type') === 'video'
            && contextNumber(operation, 'media_item_id') === scope.id
    }
    if (!scope.slug) return false
    if (scope.kind === 'episode') return contextString(operation, 'episode_slug') === scope.slug
    if (scope.kind === 'movie') return contextString(operation, 'movie_slug') === scope.slug
    return contextString(operation, 'collection_slug') === scope.slug
}

function useMediaDownloadPresentation(scope: MediaDownloadScope) {
    const enabled = scope.kind === 'all' || (scope.kind === 'video' ? scope.id !== undefined : Boolean(scope.slug))
    const domainQuery = useQuery({
        queryKey: mediaDownloadScopeKey(scope),
        enabled,
        queryFn: async ({signal}) => {
            const value = await fetchJSON<unknown[]>(
                mediaDownloadScopeUrl(scope),
                signal,
            )
            return MediaDownloadViewReadSchema.array().parse(value)
        },
        refetchOnMount: 'always',
    })
    const {data: pullData} = useFrontendPuller()
    const operations = (pullData?.operations ?? []).filter(
        (operation) => operationMatchesMediaDownloadScope(operation, scope),
    )

    const data = useMemo(() => {
        if (domainQuery.data === undefined && operations.length === 0) return undefined

        const downloads = new Map<number, MediaDownloadDomainViewRead>()
        for (const download of domainQuery.data ?? []) downloads.set(download.id, download)
        for (const operation of operations) {
            if (operation.kind !== 'media.download' || operation.resourceId == null) continue
            if (!downloads.has(operation.resourceId)) {
                const synthetic = syntheticDownload(operation)
                if (synthetic) downloads.set(synthetic.id, synthetic)
            }
        }

        return [...downloads.values()]
            .map((download) => presentDownload(
                download,
                operationForDownload(operations, download.id),
            ))
            .sort((left, right) => right.id - left.id)
    }, [domainQuery.data, operations])

    return {
        ...domainQuery,
        data,
        hasDomainData: domainQuery.data !== undefined,
    }
}

export function useEpisodeDownloads(episodeSlug?: string) {
    return useMediaDownloadPresentation({kind: 'episode', slug: episodeSlug})
}

export function useMovieDownloads(movieSlug?: string) {
    return useMediaDownloadPresentation({kind: 'movie', slug: movieSlug})
}

export function useVideoDownloads(videoId?: number) {
    return useMediaDownloadPresentation({kind: 'video', id: videoId})
}

export function useCollectionDownloads(collectionSlug?: string) {
    return useMediaDownloadPresentation({kind: 'collection', slug: collectionSlug})
}

export function useMediaDownloadsView() {
    return useMediaDownloadPresentation({kind: 'all'})
}


export type MediaDownloadCollectionOrder = 'workflow' | 'recent'

export type MediaDownloadCollectionQuery = {
    statuses?: readonly string[]
    order?: MediaDownloadCollectionOrder
    initialCount?: number
    batchSize?: number
    enabled?: boolean
}

const MEDIA_DOWNLOAD_COLLECTION_PREFIX = ['mediaDownloads'] as const

const ACTIVE_OR_QUEUED_DOWNLOAD_STATUSES = new Set([
    'pending', 'downloading', 'preparing', 'waiting', 'canceling', 'local_processing',
])

function mediaDownloadStatusFilterContains(
    source: unknown,
    target: readonly string[],
): boolean {
    if (source === null) return true
    if (!Array.isArray(source)) return false
    const sourceStatuses = new Set(
        source.filter((value): value is string => typeof value === 'string'),
    )
    return target.every((status) => sourceStatuses.has(status))
}

export function deriveMediaDownloadCollectionPlaceholder(
    queryClient: QueryClient,
    {
        statuses,
        order,
        initialCount,
        operations = [],
    }: {
        statuses: readonly string[] | undefined
        order: MediaDownloadCollectionOrder
        initialCount: number
        operations?: TaskOperationRead[]
    },
): InfiniteData<
    LazyCollectionPage<MediaDownloadDomainViewRead>,
    LazyCollectionPageRequest
> | undefined {
    if (statuses === undefined) return undefined

    const targetStatuses = [...new Set(statuses)].sort()
    const targetStatusSet = new Set(targetStatuses)
    const candidates = queryClient.getQueryCache().findAll({
        queryKey: [...MEDIA_DOWNLOAD_COLLECTION_PREFIX, 'list'],
    })

    let best: {
        data: InfiniteData<
            LazyCollectionPage<MediaDownloadDomainViewRead>,
            LazyCollectionPageRequest
        >
        matchCount: number
        updatedAt: number
    } | undefined

    for (const query of candidates) {
        const key = query.queryKey
        if (
            key[0] !== MEDIA_DOWNLOAD_COLLECTION_PREFIX[0]
            || key[1] !== 'list'
            || key[3] !== order
            || !mediaDownloadStatusFilterContains(key[2], targetStatuses)
        ) {
            continue
        }

        const sourceStatuses = key[2]
        if (
            Array.isArray(sourceStatuses)
            && sourceStatuses.length === targetStatuses.length
            && targetStatuses.every((status, index) => sourceStatuses[index] === status)
        ) {
            continue
        }

        const source = query.state.data as InfiniteData<
            LazyCollectionPage<MediaDownloadDomainViewRead>,
            LazyCollectionPageRequest
        > | undefined
        if (!source?.pages.length) continue

        const contiguous = contiguousLazyCollectionItems(source.pages)
        if (!contiguous) continue

        const firstPage = source.pages[0]
        const facets = firstPage.facets
        const targetTotal = facets
            ? targetStatuses.reduce((total, status) => total + (facets[status] ?? 0), 0)
            : contiguous.complete
                ? undefined
                : null
        if (targetTotal === null) continue

        const byId = new Map<number, MediaDownloadDomainViewRead>()
        for (const download of contiguous.items) byId.set(download.id, download)

        const matching = [...byId.values()]
            .map((download) => ({
                download,
                presented: presentDownload(
                    download,
                    operationForDownload(operations, download.id),
                ),
            }))
            .filter(({presented}) => targetStatusSet.has(String(presented.downloadStatus)))

        const total = targetTotal ?? matching.length
        const items = matching.slice(0, Math.min(initialCount, total))
            .map(({download}) => download)

        if (items.length === 0 && total > 0) continue

        const placeholder: InfiniteData<
            LazyCollectionPage<MediaDownloadDomainViewRead>,
            LazyCollectionPageRequest
        > = {
            pages: [{
                items,
                total,
                limit: initialCount,
                nextCursor: null,
                previousCursor: null,
                revision: firstPage.revision,
                facets: firstPage.facets,
                // Bulk-action counts depend on the exact filtered collection and
                // are intentionally left for the authoritative backend response.
                actions: {},
            }],
            pageParams: [{cursor: null, limit: initialCount}],
        }

        const score = items.length
        if (
            best === undefined
            || score > best.matchCount
            || (score === best.matchCount && query.state.dataUpdatedAt > best.updatedAt)
        ) {
            best = {
                data: placeholder,
                matchCount: score,
                updatedAt: query.state.dataUpdatedAt,
            }
        }
    }

    return best?.data
}

export function useMediaDownloadsCollection({
    statuses,
    order = 'workflow',
    initialCount = 50,
    batchSize = 50,
    enabled: wanted = true,
}: MediaDownloadCollectionQuery = {}) {
    const enabled = wanted && can('managed_downloads')
    const normalizedStatuses = useMemo(
        () => downloadStatusesForApi(statuses),
        [statuses],
    )
    const {data: pullData} = useFrontendPuller()
    const operations = (pullData?.operations ?? []).filter(
        (operation) => operation.kind === 'media.download',
    )
    const queryClient = useQueryClient()
    const lastActiveOrderSignature = useRef<string | null>(null)
    const activeOrderSignature = operations
        .filter((operation) => ACTIVE_OPERATION_STATUSES.has(operation.status))
        .map((operation) => `${operation.id}:${operation.status}:${operation.startedAt ?? ''}`)
        .sort()
        .join('|')

    // With local reordering disabled, fetch authoritative backend positions
    // when operations enter/leave the active queue. Progress-only pulls do
    // not change this signature and should not trigger an extra page request.
    useEffect(() => {
        if (
            !enabled || !pullData
            || (
                normalizedStatuses !== undefined
                && !normalizedStatuses.some((status) => ACTIVE_OR_QUEUED_DOWNLOAD_STATUSES.has(status))
            )
        ) return
        if (lastActiveOrderSignature.current === null) {
            lastActiveOrderSignature.current = activeOrderSignature
            return
        }
        if (lastActiveOrderSignature.current === activeOrderSignature) return
        lastActiveOrderSignature.current = activeOrderSignature
        void queryClient.invalidateQueries({
            queryKey: lazyCollectionQueryKey(
                MEDIA_DOWNLOAD_COLLECTION_PREFIX,
                [normalizedStatuses ?? null, order],
                initialCount,
                batchSize,
            ),
            exact: true,
            refetchType: 'active',
        })
    }, [
        activeOrderSignature, enabled, pullData, queryClient,
        normalizedStatuses, order, initialCount, batchSize,
    ])

    const collection = useLazyCollection<MediaDownloadDomainViewRead>({
        collectionPrefix: MEDIA_DOWNLOAD_COLLECTION_PREFIX,
        queryKey: [normalizedStatuses ?? null, order] as const,
        initialCount,
        batchSize,
        enabled,
        // Refetch cached filter variants when selected while keeping their rows visible.
        // This leaves TanStack Query's normal sequential infinite-page refresh intact.
        staleTime: 0,
        derivePlaceholderData: (queryClient) => deriveMediaDownloadCollectionPlaceholder(
            queryClient,
            {
                statuses: normalizedStatuses,
                order,
                initialCount,
                operations,
            },
        ),
        fetchPage: async ({cursor, limit}, signal) => {
            const params = new URLSearchParams({
                order,
                limit: String(limit),
            })
            if (cursor) params.set('cursor', cursor)
            for (const status of normalizedStatuses ?? []) params.append('status', status)
            return MediaDownloadPageReadSchema.parse(await fetchJSON<unknown>(
                `${(window as any).appConfig.API_URL}/media-downloads/as-view/page?${params}`,
                signal,
            ))
        },
    })

    const data = useMemo(() => {
        const downloads = new Map<number, MediaDownloadDomainViewRead>()
        for (const download of collection.items) downloads.set(download.id, download)

        const presented = [...downloads.values()]
            .map((download) => presentDownload(
                download,
                operationForDownload(operations, download.id),
            ))
            .filter((download) => (
                normalizedStatuses === undefined
                || normalizedStatuses.includes(String(download.downloadStatus))
            ))
        return presented
    }, [collection.items, normalizedStatuses, operations])

    return {
        ...collection,
        data,
    }
}

export function applyMediaDownloadQueuePositions(
    queryClient: QueryClient,
    positions: Record<number, number>,
) {
    updateLazyCollectionEntities<MediaDownloadDomainViewRead>(
        queryClient,
        MEDIA_DOWNLOAD_COLLECTION_PREFIX,
        (download) => {
            const queuePosition = positions[download.id] ?? null
            if ((download.queuePosition ?? null) === queuePosition) return download
            return {...download, queuePosition}
        },
    )
}

// Prefetch core data to warm the cache on app start
/** Warm the lists the pages share, only the ones the signed-in person may read. */
export function prefetchCoreData(qc: QueryClient) {
    const library = can('library')
    if (library) void qc
        .prefetchQuery(collectionsQueryOptions())
        .then(() => {
            const collections = qc.getQueryData<CollectionRead[]>(collectionsQueryOptions().queryKey)
            if (collections) saveCollectionsToStorage(collections)
        })
    if (library) void qc.prefetchQuery({
        queryKey: ['movies'],
        queryFn: ({signal}) => fetchParsed(
            `${(window as any).appConfig.API_URL}/movies`,
            MovieReadSchema.array(),
            signal,
        ),
    })
    if (profileListsReadable('local_media_profiles')) void qc
        .prefetchQuery({
            queryKey: ['localMediaProfiles'],
            queryFn: ({signal}) => fetchParsed(
                `${(window as any).appConfig.API_URL}/local-media-profiles`,
                LocalMediaProfileReadSchema.array(),
                signal,
            ),
        })
        .then(() => {
            const profiles = qc.getQueryData<LocalMediaProfileRead[]>(['localMediaProfiles'])
            if (profiles) saveProfilesToStorage(profiles)
        })
    if (profileListsReadable('download_profiles')) void qc.prefetchQuery({
        queryKey: ['downloadProfilesView'],
        queryFn: ({signal}) => fetchParsed(
            `${(window as any).appConfig.API_URL}/download-profiles/as-view`,
            DownloadProfileReadViewSchema.array(),
            signal,
        ),
    })
    const streamProfiles = can('stream_profiles') || can('library', 'manage')
    if (streamProfiles) void qc.prefetchQuery({
        queryKey: ['rssStreamProfiles'],
        queryFn: ({signal}) => fetchParsed(
            `${(window as any).appConfig.API_URL}/rss-stream-profiles`,
            RssStreamProfileReadSchema.array(),
            signal,
        ),
    })
    if (streamProfiles) void qc.prefetchQuery({
        queryKey: ['streamProfilesView'],
        queryFn: ({signal}) => fetchParsed(
            `${(window as any).appConfig.API_URL}/stream-profiles/as-view`,
            StreamProfileReadViewSchema.array(),
            signal,
        ),
    })
}
