import {CollectionTypeReg, CollectionTypeValue} from '../../types/collection'
import {useFilterChipPress} from '../../lib/useFilterChipPress'

const DEFAULT_COLLECTION_TYPE_FILTER = new Set<CollectionTypeValue>(CollectionTypeReg.values)

export function createDefaultCollectionTypeFilter(): Set<CollectionTypeValue> {
    return new Set(DEFAULT_COLLECTION_TYPE_FILTER)
}

function setsEqual(a: ReadonlySet<CollectionTypeValue>, b: ReadonlySet<CollectionTypeValue>): boolean {
    if (a.size !== b.size) return false
    for (const value of a) if (!b.has(value)) return false
    return true
}

export function matchesCollectionTypeFilter(
    type: unknown,
    selectedTypes: ReadonlySet<CollectionTypeValue>,
): boolean {
    const normalized = CollectionTypeReg.normalize(type)
    return normalized !== null && selectedTypes.has(normalized)
}

type CollectionTypeFilterProps = {
    selectedTypes: ReadonlySet<CollectionTypeValue>
    onChange: (selectedTypes: Set<CollectionTypeValue>) => void
    ariaLabel?: string
}

export default function CollectionTypeFilter({
    selectedTypes,
    onChange,
    ariaLabel = 'Filter collections by type',
}: CollectionTypeFilterProps) {
    const filterPress = useFilterChipPress()

    const toggleType = (type: CollectionTypeValue) => {
        const next = new Set(selectedTypes)
        if (next.has(type)) next.delete(type)
        else next.add(type)
        onChange(next)
    }

    const pressType = (type: CollectionTypeValue) => {
        filterPress.press(
            type,
            () => toggleType(type),
            () => onChange(new Set([type])),
        )
    }

    return (
        <div className="filter-chip-group" role="group" aria-label={ariaLabel}>
            {CollectionTypeReg.options.map((option) => (
                <button
                    key={option.value}
                    type="button"
                    className="filter-chip"
                    aria-pressed={selectedTypes.has(option.value)}
                    onClick={() => pressType(option.value)}
                >
                    {option.label}
                </button>
            ))}
            {!setsEqual(selectedTypes, DEFAULT_COLLECTION_TYPE_FILTER) && (
                <button
                    type="button"
                    className="filter-chip-reset"
                    onClick={() => {
                        filterPress.reset()
                        onChange(createDefaultCollectionTypeFilter())
                    }}
                >
                    Reset filters
                </button>
            )}
        </div>
    )
}
