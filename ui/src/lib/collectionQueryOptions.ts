import {queryOptions, type QueryClient} from '@tanstack/react-query'

import {EpisodeReadViewPageSchema} from '../types/schemas/episode'
import {SeasonReadSchema} from '../types/schemas/season'
import {CollectionRead, CollectionReadSchema} from '../types/schemas/collection'
import {apiUrl} from './api'

async function fetchParsed<T>(
  url: string,
  schema: {parse(value: unknown): T},
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(url, {signal, credentials: 'include'})
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return schema.parse(await response.json())
}

export function collectionsQueryOptions() {
  return queryOptions({
    queryKey: ['collections'] as const,
    queryFn: ({signal}) => fetchParsed(
      `${apiUrl()}/collections`,
      CollectionReadSchema.array(),
      signal,
    ),
    refetchOnMount: 'always' as const,
  })
}

export function collectionQueryOptions(id: string | undefined, queryClient: QueryClient) {
  return queryOptions({
    queryKey: ['collection', id] as const,
    queryFn: ({signal}) => fetchParsed(
      `${apiUrl()}/collections/${encodeURIComponent(id!)}`,
      CollectionReadSchema,
      signal,
    ),
    initialData: () => {
      if (!id) return undefined
      const collections = queryClient.getQueryData<CollectionRead[]>(collectionsQueryOptions().queryKey)
      return collections?.find((collection) => collection.slug === id)
    },
    initialDataUpdatedAt: () => queryClient.getQueryState(collectionsQueryOptions().queryKey)?.dataUpdatedAt,
  })
}

export function seasonsQueryOptions(collectionSlug: string | undefined) {
  return queryOptions({
    queryKey: ['seasons', collectionSlug] as const,
    queryFn: ({signal}) => fetchParsed(
      `${apiUrl()}/collections/${encodeURIComponent(collectionSlug!)}/seasons`,
      SeasonReadSchema.array(),
      signal,
    ),
    refetchOnMount: 'always' as const,
  })
}


export const COLLECTION_EPISODE_PREVIEW_SIZE = 15

export const episodeQueryKeys = {
  all: ['episodes'] as const,
  forCollection: (collectionSlug: string | undefined) => ['episodes', collectionSlug] as const,
  preview: (
    collectionSlug: string | undefined,
    limit: number,
  ) => ['episodes', collectionSlug, 'preview', limit] as const,
}

export async function fetchEpisodePage(
  collectionSlug: string,
  params: {cursor: string | null; limit: number; seasonId?: number; episodeTypes?: readonly string[]; hideLocked?: boolean},
  signal?: AbortSignal,
) {
  const query = new URLSearchParams({
    limit: String(params.limit),
  })
  if (params.cursor) query.set('cursor', params.cursor)
  if (params.seasonId !== undefined) {
    query.set('season_id', String(params.seasonId))
  }
  for (const episodeType of params.episodeTypes ?? []) query.append('episode_type', episodeType)
  if (params.hideLocked) query.set('hide_locked', 'true')
  return fetchParsed(
    `${apiUrl()}/episodes/as-view/by-collection-slug/${encodeURIComponent(collectionSlug)}/page?${query}`,
    EpisodeReadViewPageSchema,
    signal,
  )
}

export function episodePreviewQueryOptions(collectionSlug: string, limit: number) {
  return queryOptions({
    queryKey: episodeQueryKeys.preview(collectionSlug, limit),
    queryFn: ({signal}) => fetchEpisodePage(
      collectionSlug,
      {cursor: null, limit},
      signal,
    ),
  })
}
