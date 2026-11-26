import {useMemo, useState} from 'react'

import {can} from '../../lib/access'
import {useLibraryPreferences, useSaveLibraryPreferences} from '../../lib/queries'
import {type CollectionSortOrder, DEFAULT_COLLECTION_SORT, isCollectionSortOrder} from './CollectionSort'

const COLLECTION_SORT_STORAGE_KEY = 'libraryCollectionSort'

/** The order this browser remembers, for installs without user accounts. */
function loadBrowserCollectionSort(): CollectionSortOrder {
    try {
        const raw = localStorage.getItem(COLLECTION_SORT_STORAGE_KEY)
        const parsed: unknown = raw === null ? null : JSON.parse(raw)
        return isCollectionSortOrder(parsed) ? parsed : DEFAULT_COLLECTION_SORT
    } catch {
        return DEFAULT_COLLECTION_SORT
    }
}

/**
 * The order collections are listed in, wherever VODLoft lists them: the Library and a creator's page share it.
 * With user accounts VODLoft remembers each user's order; without them, the browser does. `known` turns true once
 * the user's saved order has loaded (or could not), so a list does not jump from one order to another.
 */
export function useCollectionSortOrder() {
    const {data: preferences, error} = useLibraryPreferences()
    const savePreferences = useSaveLibraryPreferences()
    const [browserOrder, setBrowserOrder] = useState(loadBrowserCollectionSort)
    const order = useMemo<CollectionSortOrder>(() => (preferences?.saved
        ? {by: preferences.collectionSort, reversed: preferences.collectionSortReversed}
        : browserOrder), [preferences, browserOrder])
    // A user who may not read the Library preferences never gets them, and keeps the browser's order.
    const known = !can('library') || preferences !== undefined || !!error
    const choose = (next: CollectionSortOrder) => {
        if (preferences?.saved) {
            savePreferences.mutate({collectionSort: next.by, collectionSortReversed: next.reversed})
            return
        }
        setBrowserOrder(next)
        try {
            localStorage.setItem(COLLECTION_SORT_STORAGE_KEY, JSON.stringify(next))
        } catch {
            // Without storage the order is only kept while the page is open.
        }
    }
    return {order, known, choose}
}
