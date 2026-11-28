import {StrictMode} from 'react'
import {createRoot} from 'react-dom/client'
import {QueryClient, QueryClientProvider} from '@tanstack/react-query'
// VODLoft's own look: the popup is made of the same parts as Add media and Quick download.
import '../../index.css'
import '../../pages/creator/CreatorPages.css'
import '../../components/QuickDownload/QuickDownload.css'
import '../../icons/fontAwesome'
import './popup.css'
import Popup from './Popup'

const queryClient = new QueryClient({defaultOptions: {queries: {retry: false, refetchOnWindowFocus: false}}})

createRoot(document.getElementById('root')!).render(
    <StrictMode>
        <QueryClientProvider client={queryClient}>
            <Popup/>
        </QueryClientProvider>
    </StrictMode>,
)
