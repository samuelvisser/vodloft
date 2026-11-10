import {useEffect, useState, type ReactNode} from 'react'
import FilterBar, {type ChipOption} from './FilterBar'

/** How long typing pauses before the search goes to the server. */
const SEARCH_DELAY_MS = 250

export const FORMAT_OPTIONS: ChipOption[] = [
    {value: 'video', label: 'Video'},
    {value: 'audio', label: 'Audio only'},
]

export const STATUS_OPTIONS: ChipOption[] = [
    {value: 'enabled', label: 'Enabled'},
    {value: 'disabled', label: 'Disabled'},
]

type ProfileTableFiltersProps = {
    search: string
    onSearch: (search: string) => void
    searchPlaceholder: string
    /** A control beside the search, such as a select. */
    beside?: ReactNode
    /** The ChipFilter groups. */
    children: ReactNode
    /** How many profiles match the filters. */
    total: number
    loading: boolean
    /** How many chip groups or selects narrow the list, shown on the phone's Filters button. */
    activeCount: number
    onReset: () => void
    /** Shown before the count, such as bulk edit's Select all. */
    leading?: ReactNode
}

/** The search box, filter chips and count above a profile table. On phones the chips fold behind a Filters button. */
export default function ProfileTableFilters({
    search, onSearch, searchPlaceholder, beside, children, total, loading, activeCount, onReset, leading,
}: ProfileTableFiltersProps) {
    const [typed, setTyped] = useState(search)

    // Follow a search changed from outside, such as Reset filters.
    useEffect(() => setTyped(search), [search])
    useEffect(() => {
        if (typed === search) return
        const timer = window.setTimeout(() => onSearch(typed), SEARCH_DELAY_MS)
        return () => window.clearTimeout(timer)
    }, [typed, search, onSearch])

    const filtered = activeCount > 0 || search.trim() !== ''
    const noun = total === 1 ? 'profile' : 'profiles'

    return (
        <FilterBar
            search={typed}
            onSearchChange={setTyped}
            onSearchClear={() => { setTyped(''); onSearch('') }}
            searchPlaceholder={searchPlaceholder}
            beside={beside}
            activeCount={activeCount}
            footer={(
                <div className="filter-bar-count" aria-live="polite">
                    {leading}
                    {!loading && (
                        <strong>{total.toLocaleString()} {filtered ? `matching ${noun}` : noun}</strong>
                    )}
                    {filtered && (
                        <button type="button" className="filter-chip-reset" onClick={onReset}>Reset filters</button>
                    )}
                </div>
            )}
        >
            {children}
        </FilterBar>
    )
}
