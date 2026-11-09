import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'

import SimpleSelect from '../common/SimpleSelect'
import {faIcon} from '../../icons/faIcon'
import {LibraryCollectionSortReg, type LibraryCollectionSortValue as CollectionSortBy} from '../../types/collection'
import type {CollectionReadView} from '../../types/schemas/collection'
import './CollectionSort.css'

/** How the Library lists its Collections: by what, and whether that order is turned around. */
export type CollectionSortOrder = {by: CollectionSortBy, reversed: boolean}

export const DEFAULT_COLLECTION_SORT: CollectionSortOrder = {by: 'often_used', reversed: false}

/** How each order reads, as it starts and turned around. */
const DIRECTION_LABELS: Record<CollectionSortBy, [string, string]> = {
    often_used: ['Most opened first', 'Least opened first'],
    name: ['A to Z', 'Z to A'],
    release_date: ['Newest first', 'Oldest first'],
    added_at: ['Newest first', 'Oldest first'],
}

const nameCollator = new Intl.Collator(undefined, {sensitivity: 'base', numeric: true})

export function compareCollectionNames(a: CollectionReadView, b: CollectionReadView) {
    return nameCollator.compare(a.title, b.title)
}

/** The value an order compares first, largest first; null sorts last whichever way the order goes. */
function sortKey(collection: CollectionReadView, by: CollectionSortBy): number | null {
    switch (by) {
        case 'often_used':
            return collection.openCount
        case 'release_date':
            return collection.firstPublishedDate?.getTime() ?? null
        case 'added_at':
            return collection.createdAt.getTime()
        case 'name':
            return 0
    }
}

/** Compares two Collections in the chosen order, and by name where that order ties. */
export function compareCollections(a: CollectionReadView, b: CollectionReadView, order: CollectionSortOrder) {
    const direction = order.reversed ? -1 : 1
    if (order.by === 'name') return direction * compareCollectionNames(a, b)

    const aKey = sortKey(a, order.by)
    const bKey = sortKey(b, order.by)
    if (aKey !== bKey) {
        if (aKey === null) return 1
        if (bKey === null) return -1
        return direction * (bKey - aKey)
    }
    return compareCollectionNames(a, b)
}

export function isCollectionSortOrder(value: unknown): value is CollectionSortOrder {
    if (typeof value !== 'object' || value === null) return false
    const {by, reversed} = value as Record<string, unknown>
    return typeof by === 'string' && LibraryCollectionSortReg.values.includes(by as CollectionSortBy) && typeof reversed === 'boolean'
}

type CollectionSortProps = {
    order: CollectionSortOrder
    onChange: (order: CollectionSortOrder) => void
    /** While searching, the best matches come first and the chosen order waits. */
    searching: boolean
}

export default function CollectionSort({order, onChange, searching}: CollectionSortProps) {
    const direction = DIRECTION_LABELS[order.by][order.reversed ? 1 : 0]
    return (
        <div className={`collection-sort${searching ? ' is-searching' : ''}`} role="group" aria-label="Sort collections">
            <SimpleSelect
                inputId="library-collection-sort"
                aria-label="Sort collections by"
                className="collection-sort-select"
                registry={LibraryCollectionSortReg}
                value={searching ? null : order.by}
                placeholder={<span className="collection-sort-value"><span className="collection-sort-label">Sort:</span> Best match</span>}
                isDisabled={searching}
                onChange={(by) => onChange({by: by as CollectionSortBy, reversed: false})}
                formatOptionLabel={(option, {context}) => context === 'value'
                    ? (
                        <span className="collection-sort-value">
                            <FontAwesomeIcon icon={order.reversed ? faIcon('fass', 'arrow-up-short-wide') : faIcon('fass', 'arrow-down-wide-short')} aria-hidden="true"/>
                            <span className="collection-sort-label">Sort:</span> {option.label}
                        </span>
                    )
                    : option.label}
            />
            {!searching && (
                <button
                    type="button"
                    className="collection-sort-direction"
                    onClick={() => onChange({...order, reversed: !order.reversed})}
                    aria-label={`${direction}, turn the order around`}
                    title={`${direction}, click to turn around`}
                >
                    <FontAwesomeIcon icon={order.reversed ? faIcon('fass', 'arrow-up') : faIcon('fass', 'arrow-down')} aria-hidden="true"/>
                </button>
            )}
        </div>
    )
}
