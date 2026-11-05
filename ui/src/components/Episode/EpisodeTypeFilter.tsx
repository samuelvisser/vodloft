import {useFilterChipPress} from '../../lib/useFilterChipPress'
import type {EpisodeTagRead} from '../../types/schemas/source'

type EpisodeTypeFilterProps = {
    /** The episode tags present in the list being filtered. */
    tags: readonly EpisodeTagRead[]
    /** The selected tag keys; empty means every type. */
    selected: ReadonlySet<string>
    onChange: (selected: Set<string>) => void
    ariaLabel?: string
}

/** Filter chips per episode type, such as Video, Short and Livestream. Hidden while every episode has one type. */
export default function EpisodeTypeFilter({tags, selected, onChange, ariaLabel = 'Filter episodes by type'}: EpisodeTypeFilterProps) {
    const filterPress = useFilterChipPress()
    if (tags.length < 2) return null

    const keys = tags.map((tag) => tag.key)
    const isSelected = (key: string) => selected.size === 0 || selected.has(key)
    const toggle = (key: string) => {
        const next = new Set(selected.size === 0 ? keys : selected)
        if (next.has(key)) next.delete(key)
        else next.add(key)
        onChange(next.size === keys.length ? new Set() : next)
    }

    return (
        <div className="filter-chip-group" role="group" aria-label={ariaLabel}>
            {tags.map((tag) => (
                <button
                    key={tag.key}
                    type="button"
                    className="filter-chip"
                    aria-pressed={isSelected(tag.key)}
                    title={tag.help}
                    onClick={() => filterPress.press(tag.key, () => toggle(tag.key), () => onChange(new Set([tag.key])))}
                >
                    {tag.label}
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
                    All types
                </button>
            )}
        </div>
    )
}
