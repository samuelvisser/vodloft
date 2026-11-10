import {useState, type ReactNode} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import {useFilterChipPress} from '../../lib/useFilterChipPress'
import {ClearInputButton} from './ClearInputButton'

export type ChipOption = {value: string, label: string}

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
        <div className="filter-bar-group" role="group" aria-label={label}>
            <span className="filter-bar-label" aria-hidden="true">{label}</span>
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

type FilterBarProps = {
    /** What the search box holds. */
    search: string
    onSearchChange: (search: string) => void
    /** Shown in the empty search box, and read out as its name. */
    searchPlaceholder: string
    /** Runs when the search is cleared with its button; by default the search just changes to empty. */
    onSearchClear?: () => void
    /** A control beside the search, such as a select. On phones it folds away with the chips. */
    beside?: ReactNode
    /** The ChipFilter groups. */
    children?: ReactNode
    /** Whether there is anything to fold away; without it the phone's Filters button is left out. */
    hasFilters?: boolean
    /** How many chip groups or selects narrow the list, shown on the phone's Filters button. */
    activeCount: number
    /** Shown under the chips, such as a count of what matches. */
    footer?: ReactNode
    className?: string
}

/** A search box with filter chips under it. On phones the chips and the control beside the search fold behind a Filters button. */
export default function FilterBar({
    search, onSearchChange, searchPlaceholder, onSearchClear, beside, children, hasFilters = true, activeCount, footer, className,
}: FilterBarProps) {
    const [open, setOpen] = useState(false)

    return (
        <div className={`filter-bar${className ? ` ${className}` : ''}`}>
            <div className={`filter-bar-top${hasFilters ? '' : ' no-filters'}`}>
                <label className="browse-search">
                    <span className="sr-only">{searchPlaceholder}</span>
                    <FontAwesomeIcon icon={faIcon('fass', 'magnifying-glass')} aria-hidden="true"/>
                    <input
                        enterKeyHint="search"
                        value={search}
                        onChange={(event) => onSearchChange(event.target.value)}
                        placeholder={searchPlaceholder}
                    />
                    {search && <ClearInputButton label="Clear the search" onClear={onSearchClear ?? (() => onSearchChange(''))}/>}
                </label>
                {hasFilters && (
                    <button
                        type="button"
                        className={`btn filter-bar-toggle${activeCount ? ' is-active' : ''}`}
                        aria-expanded={open}
                        onClick={() => setOpen(!open)}
                    >
                        <FontAwesomeIcon icon={faIcon('fass', 'filter')} aria-hidden="true"/>
                        <span>Filters</span>
                        {activeCount > 0 && <span className="filter-bar-badge" aria-label={`${activeCount} on`}>{activeCount}</span>}
                    </button>
                )}
                {beside && <div className={`filter-bar-beside${open ? ' is-open' : ''}`}>{beside}</div>}
            </div>
            {children && <div className={`filter-bar-chips${open ? ' is-open' : ''}`}>{children}</div>}
            {footer}
        </div>
    )
}
