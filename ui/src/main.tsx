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
import { loadAppConfig } from './general_utils.js'
import { loadPublicConfig } from './lib/publicConfig'
import { router } from './router'

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

  const rootEl = document.getElementById('root') as HTMLElement
  createRoot(rootEl).render(
    <React.StrictMode>
      <QueryClientProvider client={queryClient}>
        <Toaster position="top-right" />
        <RouterProvider router={router} />
      </QueryClientProvider>
    </React.StrictMode>,
  )


}
void bootstrap()
