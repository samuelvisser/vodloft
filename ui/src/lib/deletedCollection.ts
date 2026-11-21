import type {QueryClient} from '@tanstack/react-query'

import type {CollectionRead} from '../types/schemas/collection'
import {removeEpisodePreviewFromStorage, removeSeasonsFromStorage, saveCollectionsToStorage} from './cache'
import {collectionsQueryOptions, episodeQueryKeys} from './collectionQueryOptions'

/**
 * Forget a collection that no longer exists, in this tab and in the browser's storage.
 *
 * A collection page starts from the cached collection list, and that list is also kept in the browser's storage, so
 * a deleted collection that stays in it keeps showing until the list happens to be fetched again. Its creator's page
 * and the Library also list it until they are fetched again.
 *
 * ``keepCollectionQuery`` leaves the collection's own query in place, for a page that is showing it: removing a query
 * that a page observes makes the page create it again at once.
 */
export async function forgetDeletedCollection(
  queryClient: QueryClient,
  slug: string,
  {keepCollectionQuery = false}: {keepCollectionQuery?: boolean} = {},
) {
  removeEpisodePreviewFromStorage(slug)
  removeSeasonsFromStorage(slug)

  const own = [
    ...(keepCollectionQuery ? [] : [['collection', slug]]),
    ['seasons', slug],
    episodeQueryKeys.forCollection(slug),
  ]
  await Promise.all(own.map((queryKey) => queryClient.cancelQueries({queryKey})))
  for (const queryKey of own) queryClient.removeQueries({queryKey})

  const listKey = collectionsQueryOptions().queryKey
  const collections = queryClient.getQueryData<CollectionRead[]>(listKey)
  if (collections?.some((collection) => collection.slug === slug)) {
    const left = collections.filter((collection) => collection.slug !== slug)
    queryClient.setQueryData(listKey, left)
    saveCollectionsToStorage(left)
  }

  // Everything that lists collections: the Library, and every creator's page and the episodes it shows.
  await Promise.all([
    queryClient.invalidateQueries({queryKey: listKey}),
    queryClient.invalidateQueries({queryKey: ['collectionsView']}),
    queryClient.invalidateQueries({queryKey: ['libraryCounts']}),
    queryClient.invalidateQueries({queryKey: ['recentlyIndexedEpisodes']}),
    queryClient.invalidateQueries({queryKey: ['creators']}),
    queryClient.invalidateQueries({queryKey: ['creator']}),
  ])
}
