// Lightweight browser persistence for data that materially improves cold-page loads.
// Collection caches retain only a bounded compact episode preview; full collection histories are paged from the
// local API as the user scrolls. Episode detail pages still fetch the complete episode record.

import {LocalMediaProfileRead, LocalMediaProfileReadSchema} from "../types/schemas/local_media_profile";
import {EpisodeReadView, EpisodeReadViewSchema} from "../types/schemas/episode";
import {SeasonRead, SeasonReadSchema} from "../types/schemas/season";
import {CollectionRead, CollectionReadSchema} from "../types/schemas/collection";

const STORAGE_PREFIX = 'wl_rq_v1:'
const KEY_COLLECTIONS = STORAGE_PREFIX + 'collections'
const KEY_PROFILES = STORAGE_PREFIX + 'localMediaProfiles'

const COLLECTION_CACHE_PREFIX = 'wl_collection_cache_v3:'
const COLLECTION_CACHE_VERSION = 6
const KEY_EPISODES_PREFIX = COLLECTION_CACHE_PREFIX + 'episodes:'
const KEY_EPISODES_META_PREFIX = COLLECTION_CACHE_PREFIX + 'episodes-meta:'
const KEY_SEASONS_PREFIX = COLLECTION_CACHE_PREFIX + 'seasons:'
const KEY_SEASONS_META_PREFIX = COLLECTION_CACHE_PREFIX + 'seasons-meta:'

type CacheMetadata = {
  version: number
  fetchedAt: number
  total?: number
}

type MemoryEntry<T> = {
  data: T
  fetchedAt: number
  total?: number
}

const episodePreviewMemoryCache = new Map<string, MemoryEntry<EpisodeReadView[]>>()
const seasonMemoryCache = new Map<string, MemoryEntry<SeasonRead[]>>()

function safeJsonParse(raw: string | null): unknown | undefined {
  if (!raw) return undefined
  try {
    return JSON.parse(raw)
  } catch {
    return undefined
  }
}

function safeGetItem(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function safeSetItem(key: string, value: string): boolean {
  try {
    localStorage.setItem(key, value)
    return true
  } catch {
    return false
  }
}

function safeRemoveItem(key: string) {
  try {
    localStorage.removeItem(key)
  } catch {
    // Browser storage is an optimization only.
  }
}

function parseStored<T>(raw: string | null, schema: {safeParse(value: unknown): {success: boolean; data?: T}}): T | undefined {
  const value = safeJsonParse(raw)
  if (value === undefined) return undefined
  const parsed = schema.safeParse(value)
  return parsed.success ? parsed.data : undefined
}

function parseCacheMetadata(raw: string | null): CacheMetadata | undefined {
  const value = safeJsonParse(raw)
  if (!value || typeof value !== 'object') return undefined
  const record = value as Record<string, unknown>
  if (record.version !== COLLECTION_CACHE_VERSION) return undefined
  if (typeof record.fetchedAt !== 'number' || !Number.isFinite(record.fetchedAt)) return undefined
  if (
    record.total !== undefined
    && (typeof record.total !== 'number' || !Number.isInteger(record.total) || record.total < 0)
  ) return undefined
  return {
    version: COLLECTION_CACHE_VERSION,
    fetchedAt: record.fetchedAt,
    total: record.total as number | undefined,
  }
}

function collectionCacheKey(prefix: string, collectionSlug: string) {
  return prefix + encodeURIComponent(collectionSlug)
}

function episodesStorageKey(collectionSlug: string) {
  return collectionCacheKey(KEY_EPISODES_PREFIX, collectionSlug)
}

function episodesMetadataKey(collectionSlug: string) {
  return collectionCacheKey(KEY_EPISODES_META_PREFIX, collectionSlug)
}

function seasonsStorageKey(collectionSlug: string) {
  return collectionCacheKey(KEY_SEASONS_PREFIX, collectionSlug)
}

function seasonsMetadataKey(collectionSlug: string) {
  return collectionCacheKey(KEY_SEASONS_META_PREFIX, collectionSlug)
}

function cacheMetadata(fetchedAt: number, total?: number): CacheMetadata {
  return {version: COLLECTION_CACHE_VERSION, fetchedAt, total}
}

function compactEpisodes(data: EpisodeReadView[]): EpisodeReadView[] {
  return data.map((episode) => ({
    id: episode.id,
    sourceKey: episode.sourceKey,
    sourceFeatures: episode.sourceFeatures,
    collectionId: episode.collectionId,
    seasonId: episode.seasonId,
    index: episode.index,
    episodeIdentifier: episode.episodeIdentifier,
    dwEpisodeNumber: episode.dwEpisodeNumber,
    episodeType: episode.episodeType,
    episodeExtraType: episode.episodeExtraType,
    episodeNumber: episode.episodeNumber,
    episodeSubNumber: episode.episodeSubNumber,
    episodeLabel: episode.episodeLabel,
    slug: episode.slug,
    title: episode.title,
    publishStatus: episode.publishStatus,
    drmProtected: episode.drmProtected,
    access: episode.access,
    accessRefusedAt: episode.accessRefusedAt,
    accessCheckAt: episode.accessCheckAt,
    accessLocked: episode.accessLocked,
    accessLabel: episode.accessLabel,
    accessDescription: episode.accessDescription,
    removedFromSource: episode.removedFromSource,
    thumbnailLandscapePath: episode.thumbnailLandscapePath ?? null,
    thumbnailPortraitPath: episode.thumbnailPortraitPath ?? null,
    thumbnailSquarePath: episode.thumbnailSquarePath ?? null,
  }))
}

export function loadCollectionsFromStorage(): CollectionRead[] | undefined {
  return parseStored(safeGetItem(KEY_COLLECTIONS), CollectionReadSchema.array())
}

export function saveCollectionsToStorage(data: CollectionRead[] | undefined) {
  if (!data) {
    safeRemoveItem(KEY_COLLECTIONS)
    return
  }
  safeSetItem(KEY_COLLECTIONS, JSON.stringify(data))
}

/** Return the persisted recent-episode preview so ShowPage can paint before revalidation. */
export function loadEpisodePreviewFromStorage(collectionSlug?: string): EpisodeReadView[] | undefined {
  if (!collectionSlug) return undefined

  const memory = episodePreviewMemoryCache.get(collectionSlug)
  if (memory) return memory.data

  const metadata = parseCacheMetadata(safeGetItem(episodesMetadataKey(collectionSlug)))
  if (metadata === undefined) return undefined

  const cached = parseStored(safeGetItem(episodesStorageKey(collectionSlug)), EpisodeReadViewSchema.array())
  if (cached !== undefined) {
    episodePreviewMemoryCache.set(collectionSlug, {
      data: cached,
      fetchedAt: metadata.fetchedAt,
      total: metadata.total,
    })
    return cached
  }

  return undefined
}

export function getEpisodePreviewFetchedAt(collectionSlug: string): number | undefined {
  const memory = episodePreviewMemoryCache.get(collectionSlug)
  if (memory) return memory.fetchedAt > 0 ? memory.fetchedAt : undefined

  return parseCacheMetadata(safeGetItem(episodesMetadataKey(collectionSlug)))?.fetchedAt
}

export function getEpisodePreviewTotal(collectionSlug: string): number | undefined {
  const memory = episodePreviewMemoryCache.get(collectionSlug)
  if (memory?.total !== undefined) return memory.total

  return parseCacheMetadata(safeGetItem(episodesMetadataKey(collectionSlug)))?.total
}

export function saveEpisodePreviewToStorage(
  collectionSlug: string,
  data: EpisodeReadView[] | undefined,
  fetchedAt?: number,
  total?: number,
) {
  if (data === undefined) {
    removeEpisodePreviewFromStorage(collectionSlug)
    return
  }

  const existing = episodePreviewMemoryCache.get(collectionSlug)
  const effectiveFetchedAt = fetchedAt ?? existing?.fetchedAt ?? Date.now()
  const effectiveTotal = total ?? existing?.total
  if (
    existing?.data === data
    && existing.fetchedAt === effectiveFetchedAt
    && existing.total === effectiveTotal
  ) return

  episodePreviewMemoryCache.set(collectionSlug, {
    data,
    fetchedAt: effectiveFetchedAt,
    total: effectiveTotal,
  })

  const persisted = safeSetItem(episodesStorageKey(collectionSlug), JSON.stringify(compactEpisodes(data)))
  if (persisted) {
    safeSetItem(
      episodesMetadataKey(collectionSlug),
      JSON.stringify(cacheMetadata(effectiveFetchedAt, effectiveTotal)),
    )
  }
}

export function removeEpisodePreviewFromStorage(collectionSlug: string) {
  episodePreviewMemoryCache.delete(collectionSlug)
  safeRemoveItem(episodesStorageKey(collectionSlug))
  safeRemoveItem(episodesMetadataKey(collectionSlug))
}

export function loadSeasonsFromStorage(collectionSlug?: string): SeasonRead[] | undefined {
  if (!collectionSlug) return undefined

  const memory = seasonMemoryCache.get(collectionSlug)
  if (memory) return memory.data

  const cached = parseStored(safeGetItem(seasonsStorageKey(collectionSlug)), SeasonReadSchema.array())
  if (cached === undefined) return undefined

  const fetchedAt = getSeasonsCacheFetchedAt(collectionSlug) ?? 0
  seasonMemoryCache.set(collectionSlug, {data: cached, fetchedAt})
  return cached
}

export function getSeasonsCacheFetchedAt(collectionSlug: string): number | undefined {
  const memory = seasonMemoryCache.get(collectionSlug)
  if (memory) return memory.fetchedAt > 0 ? memory.fetchedAt : undefined

  if (safeGetItem(seasonsStorageKey(collectionSlug)) === null) return undefined
  return parseCacheMetadata(safeGetItem(seasonsMetadataKey(collectionSlug)))?.fetchedAt
}

export function saveSeasonsToStorage(
  collectionSlug: string,
  data: SeasonRead[] | undefined,
  fetchedAt?: number,
) {
  if (data === undefined) {
    removeSeasonsFromStorage(collectionSlug)
    return
  }

  const existing = seasonMemoryCache.get(collectionSlug)
  const effectiveFetchedAt = fetchedAt ?? existing?.fetchedAt ?? Date.now()
  if (existing?.data === data && existing.fetchedAt === effectiveFetchedAt) return

  seasonMemoryCache.set(collectionSlug, {data, fetchedAt: effectiveFetchedAt})
  const persisted = safeSetItem(seasonsStorageKey(collectionSlug), JSON.stringify(data))
  if (persisted) {
    safeSetItem(seasonsMetadataKey(collectionSlug), JSON.stringify(cacheMetadata(effectiveFetchedAt)))
  }
}

export function removeSeasonsFromStorage(collectionSlug: string) {
  seasonMemoryCache.delete(collectionSlug)
  safeRemoveItem(seasonsStorageKey(collectionSlug))
  safeRemoveItem(seasonsMetadataKey(collectionSlug))
}

export function loadProfilesFromStorage(): LocalMediaProfileRead[] | undefined {
  return parseStored(safeGetItem(KEY_PROFILES), LocalMediaProfileReadSchema.array())
}

export function saveProfilesToStorage(data: LocalMediaProfileRead[] | undefined) {
  if (!data) {
    safeRemoveItem(KEY_PROFILES)
    return
  }
  safeSetItem(KEY_PROFILES, JSON.stringify(data))
}
