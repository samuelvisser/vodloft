import React from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from 'react-hot-toast'
import './index.css'
import './reactSelectMultiselect.css'
import './mobileHeaderScroll.css'
import './icons/fontAwesome'
import { queryClient } from './lib/queryClient'
import { prefetchCoreData } from './lib/queries'
import { loadCollectionsFromStorage, loadProfilesFromStorage } from './lib/cache'
import {
  hydrateCachedSeasonQueries,
  hydrateCurrentCollectionRouteCache,
  installCollectionDataQueryPersistence,
  scheduleCollectionDataCacheWarm,
} from './lib/collectionDataCacheWarmer'
import { loadAppConfig } from './general_utils.js'
import { loadPublicConfig } from './lib/publicConfig'
import { router } from './router'
import { can, loadAccess } from './lib/access'

async function bootstrap() {
  // Load app config before anything renders
  await loadAppConfig()

  // Public config only contains auxiliary frontend metadata. A temporary API
  // failure must not prevent React from mounting and leave the page blank.
  try {
    await loadPublicConfig()
  } catch (error) {
    console.error('[publicConfig] Failed to load public config during bootstrap', error)
  }

  // Who is signed in decides what to load; App shows the sign-in page when nobody is.
  try {
    await loadAccess()
  } catch (error) {
    console.error('[access] Failed to load who is signed in during bootstrap', error)
  }
  const library = can('library')

  // Restore cached data synchronously before initial render to prevent flashes.
  const cachedCollections = library ? loadCollectionsFromStorage() : null
  if (cachedCollections) {
    queryClient.setQueryData(['collections'], cachedCollections)
    // Season lists are small and seasonal collection pages need them before rendering episode cards.
    // Hydrating them now avoids a skeleton gate without parsing every potentially-large episode list.
    hydrateCachedSeasonQueries(queryClient, cachedCollections)
  }
  const cachedProfiles = can('local_media_profiles') ? loadProfilesFromStorage() : null
  if (cachedProfiles) {
    queryClient.setQueryData(['localMediaProfiles'], cachedProfiles)
  }

  // A direct reload of a seasonal collection should get its small cached season list before React mounts.
  // Episode previews are read lazily by ShowPage so startup never parses unrelated episode data.
  if (library) hydrateCurrentCollectionRouteCache(queryClient)

  // Persist small season-query results produced by normal foreground refreshes.
  installCollectionDataQueryPersistence(queryClient)

  // Warm the existing core cache without blocking the first render.
  prefetchCoreData(queryClient)

  const rootEl = document.getElementById('root') as HTMLElement
  createRoot(rootEl).render(
    <React.StrictMode>
      <QueryClientProvider client={queryClient}>
        <Toaster position="top-right" />
        <RouterProvider router={router} />
      </QueryClientProvider>
    </React.StrictMode>,
  )

  // Warm only the bounded recent-episode preview per stale collection after first paint.
  if (library) scheduleCollectionDataCacheWarm(queryClient)
}
void bootstrap()
