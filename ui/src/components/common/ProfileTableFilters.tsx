import {useEffect, useState, type ReactNode} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import {useFilterChipPress} from '../../lib/useFilterChipPress'
import {ClearInputButton} from './ClearInputButton'

/** How long typing pauses before the search goes to the server. */
const SEARCH_DELAY_MS = 250

export type ChipOption = {value: string, label: string}

export const FORMAT_OPTIONS: ChipOption[] = [
    {value: 'video', label: 'Video'},
    {value: 'audio', label: 'Audio only'},
]

export const STATUS_OPTIONS: ChipOption[] = [
    {value: 'enabled', label: 'Enabled'},
    {value: 'disabled', label: 'Disabled'},
]

type ChipFilterProps = {
    label: string
    options: readonly ChipOption[]
    /** The selected values; empty means every option. */
    selected: readonly string[]
    onChange: (selected: string[]) => void
}

/** One labelled group of filter chips. Pressing a chip twice makes it the only one. Hidden with fewer than two options. */
export function ChipFilter({label, options, selected, onChange}: ChipFilterProps) {
    const filterPress = useFilterChipPress()
    if (options.length < 2) return null

    const values = options.map((option) => option.value)
    const isSelected = (value: string) => selected.length === 0 || selected.includes(value)
    const toggle = (value: string) => {
        const next = new Set(selected.length === 0 ? values : selected)
        if (next.has(value)) next.delete(value)
        else next.add(value)
        onChange(next.size === values.length || next.size === 0 ? [] : values.filter((item) => next.has(item)))
    }

    return (
        <div className="profile-filter-group" role="group" aria-label={label}>
            <span className="profile-filter-label" aria-hidden="true">{label}</span>
            {options.map((option) => (
                <button
                    key={option.value}
                    type="button"
                    className="filter-chip"
                    aria-pressed={isSelected(option.value)}
                    onClick={() => filterPress.press(option.value, () => toggle(option.value), () => onChange([option.value]))}
                >
                    {option.label}
                </button>
            ))}
        </div>
    )
}

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
}

/** The search box, filter chips and count above a profile table. On phones the chips fold behind a Filters button. */
export default function ProfileTableFilters({
    search, onSearch, searchPlaceholder, beside, children, total, loading, activeCount, onReset,
}: ProfileTableFiltersProps) {
    const [open, setOpen] = useState(false)
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
        <div className="profile-filters">
            <div className="profile-filters-top">
                <label className="browse-search">
                    <span className="sr-only">{searchPlaceholder}</span>
                    <FontAwesomeIcon icon={faIcon('fass', 'magnifying-glass')} aria-hidden="true"/>
                    <input
                        enterKeyHint="search"
                        value={typed}
                        onChange={(event) => setTyped(event.target.value)}
                        placeholder={searchPlaceholder}
                    />
                    {typed && <ClearInputButton label="Clear the search" onClear={() => { setTyped(''); onSearch('') }}/>}
                </label>
                <button
                    type="button"
                    className={`btn profile-filters-toggle${activeCount ? ' is-active' : ''}`}
                    aria-expanded={open}
                    onClick={() => setOpen(!open)}
                >
                    <FontAwesomeIcon icon={faIcon('fass', 'filter')} aria-hidden="true"/>
                    <span>Filters</span>
                    {activeCount > 0 && <span className="profile-filters-badge" aria-label={`${activeCount} on`}>{activeCount}</span>}
                </button>
                {beside && <div className={`profile-filters-beside${open ? ' is-open' : ''}`}>{beside}</div>}
            </div>
            <div className={`profile-filters-chips${open ? ' is-open' : ''}`}>
                {children}
            </div>
            <div className="profile-filters-count" aria-live="polite">
                {!loading && (
                    <strong>{total.toLocaleString()} {filtered ? `matching ${noun}` : noun}</strong>
                )}
                {filtered && (
                    <button type="button" className="filter-chip-reset" onClick={onReset}>Reset filters</button>
                )}
            </div>
        </div>
    )
}
