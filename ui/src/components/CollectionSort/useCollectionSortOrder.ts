import {useMemo, useState} from 'react'

import {can} from '../../lib/access'
import {useLibraryPreferences, useSaveLibraryPreferences} from '../../lib/queries'
import {type CollectionSortOrder, DEFAULT_COLLECTION_SORT, isCollectionSortOrder} from './CollectionSort'

/** Where collections are listed: each place remembers an order of its own. */
export type CollectionSortPlace = 'library' | 'creator'

/** Where each place's order is kept: the user's preferences, or this browser without user accounts. */
const PLACES = {
    library: {sort: 'collectionSort', reversed: 'collectionSortReversed', storageKey: 'libraryCollectionSort'},
    creator: {sort: 'creatorCollectionSort', reversed: 'creatorCollectionSortReversed', storageKey: 'creatorCollectionSort'},
} as const

/** The order this browser remembers, for installs without user accounts. */
function loadBrowserCollectionSort(storageKey: string): CollectionSortOrder {
    try {
        const raw = localStorage.getItem(storageKey)
        const parsed: unknown = raw === null ? null : JSON.parse(raw)
        return isCollectionSortOrder(parsed) ? parsed : DEFAULT_COLLECTION_SORT
    } catch {
        return DEFAULT_COLLECTION_SORT
    }
}

/**
 * The order a place lists collections in: the Library, or every creator page.
 * With user accounts VODLoft remembers each user's order; without them, the browser does. `known` turns true once
 * the user's saved order has loaded (or could not), so a list does not jump from one order to another.
 */
export function useCollectionSortOrder(place: CollectionSortPlace) {
    const {sort, reversed, storageKey} = PLACES[place]
    const {data: preferences, error} = useLibraryPreferences()
    const savePreferences = useSaveLibraryPreferences()
    const [browserOrder, setBrowserOrder] = useState(() => loadBrowserCollectionSort(storageKey))
    const order = useMemo<CollectionSortOrder>(() => (preferences?.saved
        ? {by: preferences[sort], reversed: preferences[reversed]}
        : browserOrder), [preferences, browserOrder, sort, reversed])
    // A user who may not read the Library preferences never gets them, and keeps the browser's order.
    const known = !can('library') || preferences !== undefined || !!error
    const choose = (next: CollectionSortOrder) => {
        if (preferences?.saved) {
            savePreferences.mutate({[sort]: next.by, [reversed]: next.reversed})
            return
        }
        setBrowserOrder(next)
        try {
            localStorage.setItem(storageKey, JSON.stringify(next))
        } catch {
            // Without storage the order is only kept while the page is open.
        }
    }
    return {order, known, choose}
}
