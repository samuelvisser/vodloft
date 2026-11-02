import {QueryClient} from '@tanstack/react-query'

import {
  getEpisodePreviewFetchedAt,
  getSeasonsCacheFetchedAt,
  loadSeasonsFromStorage,
  saveEpisodePreviewToStorage,
  saveSeasonsToStorage,
  saveCollectionsToStorage,
} from './cache'
import {
  episodePreviewQueryOptions,
  seasonsQueryOptions,
  COLLECTION_EPISODE_PREVIEW_SIZE,
  collectionsQueryOptions,
} from './collectionQueryOptions'
import {SeasonRead} from '../types/schemas/season'
import {CollectionRead} from '../types/schemas/collection'

const COLLECTION_DATA_MAX_AGE_MS = 24 * 60 * 60 * 1000
const COLLECTION_WARM_CONCURRENCY = 2

function isFresh(fetchedAt: number | undefined) {
  if (fetchedAt === undefined) return false
  return Date.now() - fetchedAt < COLLECTION_DATA_MAX_AGE_MS
}

function collectionSlugFromCurrentRoute(): string | undefined {
  if (typeof window === 'undefined') return undefined
  const match = window.location.pathname.match(/^\/show\/([^/]+)\/?$/)
  if (!match) return undefined
  try {
    return decodeURIComponent(match[1])
  } catch {
    return match[1]
  }
}

/**
 * Hydrate the small season list needed by a directly-opened seasonal collection before React mounts.
 * Episode previews stay in browser storage and ShowPage reads only its own preview on demand.
 */
export function hydrateCurrentCollectionRouteCache(queryClient: QueryClient): void {
  const collectionSlug = collectionSlugFromCurrentRoute()
  if (!collectionSlug) return

  const seasonOptions = seasonsQueryOptions(collectionSlug)
  const seasons = loadSeasonsFromStorage(collectionSlug)
  if (seasons !== undefined) {
    queryClient.setQueryData(
      seasonOptions.queryKey,
      seasons,
      {updatedAt: getSeasonsCacheFetchedAt(collectionSlug) ?? 0},
    )
  }
}

/** Season lists are small, and ShowPage needs them before it can render a seasonal episode grid. */
export function hydrateCachedSeasonQueries(queryClient: QueryClient, collections: CollectionRead[]): void {
  for (const collection of collections) {
    if (collection.episodeIdentifier !== 'seasonal') continue
    const seasons = loadSeasonsFromStorage(collection.slug)
    if (seasons === undefined) continue
    const cachedAt = getSeasonsCacheFetchedAt(collection.slug) ?? 0
    const queryKey = seasonsQueryOptions(collection.slug).queryKey
    const queryUpdatedAt = queryClient.getQueryState(queryKey)?.dataUpdatedAt ?? 0
    if (queryUpdatedAt >= cachedAt && queryClient.getQueryData(queryKey) !== undefined) continue
    queryClient.setQueryData(queryKey, seasons, {updatedAt: cachedAt})
  }
}

async function warmEpisodes(queryClient: QueryClient, collection: CollectionRead) {
  const cachedAt = getEpisodePreviewFetchedAt(collection.slug)
  if (cachedAt !== undefined && isFresh(cachedAt)) return

  const options = episodePreviewQueryOptions(collection.slug, COLLECTION_EPISODE_PREVIEW_SIZE)
  const page = await queryClient.fetchQuery({...options, staleTime: 0})
  const fetchedAt = queryClient.getQueryState(options.queryKey)?.dataUpdatedAt ?? Date.now()
  saveEpisodePreviewToStorage(collection.slug, page.items, fetchedAt, page.collectionTotal)
}

async function warmSeasons(queryClient: QueryClient, collection: CollectionRead) {
  if (collection.episodeIdentifier !== 'seasonal') return

  const options = seasonsQueryOptions(collection.slug)
  const cachedAt = getSeasonsCacheFetchedAt(collection.slug)
  const queryData = queryClient.getQueryData(options.queryKey)
  const queryUpdatedAt = queryClient.getQueryState(options.queryKey)?.dataUpdatedAt
  if (queryData !== undefined && isFresh(queryUpdatedAt ?? cachedAt)) return

  const seasons = await queryClient.fetchQuery({...options, staleTime: 0})
  const fetchedAt = queryClient.getQueryState(options.queryKey)?.dataUpdatedAt ?? Date.now()
  saveSeasonsToStorage(collection.slug, seasons, fetchedAt)
}

async function yieldToBrowser() {
  await new Promise<void>((resolve) => setTimeout(resolve, 0))
}

async function warmCollectionsWithLimitedConcurrency(
  queryClient: QueryClient,
  collections: CollectionRead[],
) {
  let nextIndex = 0

  const worker = async () => {
    while (nextIndex < collections.length) {
      const collection = collections[nextIndex]
      nextIndex += 1
      try {
        await warmSeasons(queryClient, collection)
        await warmEpisodes(queryClient, collection)
      } catch {
        // Cache warming is opportunistic. Foreground queries still surface errors normally.
      }
      await yieldToBrowser()
    }
  }

  const workerCount = Math.min(COLLECTION_WARM_CONCURRENCY, collections.length)
  await Promise.all(Array.from({length: workerCount}, () => worker()))
}

async function warmCollectionDataCache(queryClient: QueryClient) {
  const collectionOptions = collectionsQueryOptions()
  let collections = queryClient.getQueryData<CollectionRead[]>(collectionOptions.queryKey) ?? []
  hydrateCachedSeasonQueries(queryClient, collections)

  try {
    // Always resolve the current collection list in the background so newly-added collections are included.
    collections = await queryClient.fetchQuery({...collectionOptions, staleTime: 0})
    saveCollectionsToStorage(collections)
    hydrateCachedSeasonQueries(queryClient, collections)
  } catch {
    // If the API is temporarily unavailable, cached collection metadata is still useful for warming.
  }

  if (collections.length === 0) return

  // The current route owns its foreground episode request. Do not duplicate it with a preview warm.
  const currentCollectionSlug = collectionSlugFromCurrentRoute()
  const backgroundCollections = currentCollectionSlug
    ? collections.filter((collection) => (
        collection.slug !== currentCollectionSlug
        || collection.episodeIdentifier === 'seasonal'
      ))
    : collections
  await warmCollectionsWithLimitedConcurrency(queryClient, backgroundCollections)
}

const persistenceInstalledFor = new WeakSet<QueryClient>()

/** Persist successful seasonal lookup results produced by normal foreground refreshes. */
export function installCollectionDataQueryPersistence(queryClient: QueryClient): void {
  if (persistenceInstalledFor.has(queryClient)) return
  persistenceInstalledFor.add(queryClient)

  const lastPersistedAt = new Map<string, number>()
  queryClient.getQueryCache().subscribe((event) => {
    const query = event.query
    const state = query.state
    if (state.status !== 'success' || state.dataUpdatedAt <= 0 || !Array.isArray(state.data)) return

    const [kind, collectionSlug] = query.queryKey
    if (kind !== 'seasons' || typeof collectionSlug !== 'string') return

    const marker = `seasons:${collectionSlug}`
    if (lastPersistedAt.get(marker) === state.dataUpdatedAt) return
    lastPersistedAt.set(marker, state.dataUpdatedAt)
    saveSeasonsToStorage(collectionSlug, state.data as SeasonRead[], state.dataUpdatedAt)
  })
}

type IdleCapableWindow = Window & {
  requestIdleCallback?: (callback: () => void, options?: {timeout: number}) => number
}

function scheduleAfterFirstPaint(run: () => void) {
  const idleWindow = window as IdleCapableWindow
  if (idleWindow.requestIdleCallback) {
    idleWindow.requestIdleCallback(run, {timeout: 750})
  } else {
    window.setTimeout(run, 0)
  }
}

/** Start after first paint and warm only the bounded episode preview for each stale show. */
export function scheduleCollectionDataCacheWarm(queryClient: QueryClient): void {
  const run = () => {
    void warmCollectionDataCache(queryClient)
  }

  if (typeof window === 'undefined') {
    run()
    return
  }

  const schedule = () => scheduleAfterFirstPaint(run)

  if (document.visibilityState !== 'hidden') {
    schedule()
    return
  }

  const startWhenVisible = () => {
    if (document.visibilityState === 'hidden') return
    document.removeEventListener('visibilitychange', startWhenVisible)
    schedule()
  }
  document.addEventListener('visibilitychange', startWhenVisible)
}
