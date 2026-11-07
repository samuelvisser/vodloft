import {useState, type ReactNode} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import {useFilterChipPress} from '../../lib/useFilterChipPress'
import {ClearInputButton} from './ClearInputButton'

export type ChipOption = {value: string, label: string}

type ChipFilterProps = {
    label: string
    options: readonly ChipOption[]
    /** Empty means every option. */
    selected: ReadonlySet<string>
    onChange: (selected: Set<string>) => void
}

/** One labelled group of filter chips. Pressing a chip twice makes it the only one. */
export function ChipFilter({label, options, selected, onChange}: ChipFilterProps) {
    const filterPress = useFilterChipPress()
    if (options.length < 2) return null
    const keys = options.map((option) => option.value)
    const isSelected = (key: string) => selected.size === 0 || selected.has(key)
    const toggle = (key: string) => {
        const next = new Set(selected.size === 0 ? keys : selected)
        if (next.has(key)) next.delete(key)
        else next.add(key)
        onChange(next.size === keys.length || next.size === 0 ? new Set() : next)
    }
    return (
        <div className="profile-filter-group" role="group" aria-label={label}>
            <span className="profile-filter-label">{label}</span>
            {options.map((option) => (
                <button
                    key={option.value}
                    type="button"
                    className="filter-chip"
                    aria-pressed={isSelected(option.value)}
                    onClick={() => filterPress.press(option.value, () => toggle(option.value), () => onChange(new Set([option.value])))}
                >
                    {option.label}
                </button>
            ))}
        </div>
    )
}

type ProfileTableFiltersProps = {
    search: string
    onSearch: (value: string) => void
    searchPlaceholder: string
    /** Extra control beside the search, such as a select. */
    beside?: ReactNode
    children: ReactNode
    shown: number
    total: number
    noun: [string, string]
    filtered: boolean
    /** How many chip groups or selects narrow the list, for the phone's Filters button. */
    activeCount: number
    onReset: () => void
}

export default function ProfileTableFilters({
    search, onSearch, searchPlaceholder, beside, children, shown, total, noun, filtered, activeCount, onReset,
}: ProfileTableFiltersProps) {
    const [open, setOpen] = useState(false)
    return (
        <div className="profile-filters">
            <div className="profile-filters-top">
                <label className="browse-search">
                    <span className="sr-only">{searchPlaceholder}</span>
                    <FontAwesomeIcon icon={faIcon('fass', 'magnifying-glass')} aria-hidden="true"/>
                    <input
                        enterKeyHint="search"
                        value={search}
                        onChange={(event) => onSearch(event.target.value)}
                        placeholder={searchPlaceholder}
                    />
                    {search && <ClearInputButton label="Clear the search" onClear={() => onSearch('')}/>}
                </label>
                <button
                    type="button"
                    className={`btn profile-filters-toggle${activeCount ? ' is-active' : ''}`}
                    aria-expanded={open}
                    onClick={() => setOpen(!open)}
                >
                    <FontAwesomeIcon icon={faIcon('fass', 'filter')} aria-hidden="true"/>
                    <span>Filters</span>
                    {activeCount > 0 && <span className="profile-filters-badge">{activeCount}</span>}
                </button>
                {beside && <div className="profile-filters-beside">{beside}</div>}
            </div>
            <div className={`profile-filters-chips${open ? ' is-open' : ''}`}>
                {children}
            </div>
            <div className="profile-filters-count">
                <strong>
                    {filtered
                        ? `${shown.toLocaleString()} of ${total.toLocaleString()} ${total === 1 ? noun[0] : noun[1]}`
                        : `${total.toLocaleString()} ${total === 1 ? noun[0] : noun[1]}`}
                </strong>
                {filtered && (
                    <button type="button" className="filter-chip-reset" onClick={onReset}>Reset filters</button>
                )}
            </div>
        </div>
    )
}

export function matchesChips(value: string, selected: ReadonlySet<string>) {
    return selected.size === 0 || selected.has(value)
}

export function matchesWords(words: readonly string[], ...fields: (string | null | undefined)[]) {
    const haystack = fields.filter(Boolean).join(' ').toLowerCase()
    return words.every((word) => haystack.includes(word))
}

export function searchWords(search: string) {
    return search.toLowerCase().split(/\s+/).filter(Boolean)
}

export function formatKind(format: string) {
    return format === 'format_audio_only' ? 'audio' : 'video'
}

export const FORMAT_KIND_OPTIONS: ChipOption[] = [
    {value: 'video', label: 'Video'},
    {value: 'audio', label: 'Audio only'},
]

export const ENABLED_OPTIONS: ChipOption[] = [
    {value: 'enabled', label: 'Enabled'},
    {value: 'disabled', label: 'Disabled'},
]
