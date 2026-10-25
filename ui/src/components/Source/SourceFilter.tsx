import {useFilterChipPress} from '../../lib/useFilterChipPress'
import {useSourceLookup} from '../../lib/queries'

type SourceFilterProps = {
    /** Source ids present in the list being filtered. */
    sourceKeys: readonly string[]
    /** The selected Source ids; empty means every Source. */
    selected: ReadonlySet<string>
    onChange: (selected: Set<string>) => void
    ariaLabel?: string
}

/** Filter chips per Source. Hidden while everything comes from one Source. */
export default function SourceFilter({sourceKeys, selected, onChange, ariaLabel = 'Filter by source'}: SourceFilterProps) {
    const sources = useSourceLookup()
    const filterPress = useFilterChipPress()
    if (sourceKeys.length < 2) return null

    const isSelected = (key: string) => selected.size === 0 || selected.has(key)
    const toggle = (key: string) => {
        const next = new Set(selected.size === 0 ? sourceKeys : selected)
        if (next.has(key)) next.delete(key)
        else next.add(key)
        onChange(next.size === sourceKeys.length ? new Set() : next)
    }

    return (
        <div className="filter-chip-group" role="group" aria-label={ariaLabel}>
            {sourceKeys.map((key) => (
                <button
                    key={key}
                    type="button"
                    className="filter-chip"
                    aria-pressed={isSelected(key)}
                    onClick={() => filterPress.press(key, () => toggle(key), () => onChange(new Set([key])))}
                >
                    {sources.name(key)}
                </button>
            ))}
            {selected.size > 0 && (
                <button
                    type="button"
                    className="filter-chip-reset"
                    onClick={() => {
                        filterPress.reset()
                        onChange(new Set())
                    }}
                >
                    All sources
                </button>
            )}
        </div>
    )
}

export function matchesSourceFilter(sourceKey: string | null | undefined, selected: ReadonlySet<string>): boolean {
    return selected.size === 0 || (!!sourceKey && selected.has(sourceKey))
}
