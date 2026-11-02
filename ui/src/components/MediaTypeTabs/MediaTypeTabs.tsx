import type {IconProp} from '@fortawesome/fontawesome-svg-core'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'

export type MediaType = 'collections' | 'movies' | 'videos'

const TAB_LABELS: Record<MediaType, {label: string; icon: IconProp}> = {
    collections: {label: 'Collections', icon: faIcon('fass', 'tv')},
    movies: {label: 'Movies', icon: faIcon('fass', 'clapperboard')},
    videos: {label: 'Videos', icon: faIcon('fass', 'film')},
}

type MediaTypeTabsProps = {
    activeType: MediaType
    onChange: (type: MediaType) => void
    ariaLabel: string
    /** The tabs to offer, in order. */
    types?: readonly MediaType[]
    counts?: Partial<Record<MediaType, number>>
    /** A Source's own words for the tabs, where it shows its own catalogue. */
    labels?: Partial<Record<MediaType, string>>
}

export default function MediaTypeTabs({
    activeType,
    onChange,
    ariaLabel,
    types = ['collections', 'movies'],
    counts,
    labels,
}: MediaTypeTabsProps) {
    return (
        <div className="media-type-tabs browse-type-tabs" role="tablist" aria-label={ariaLabel}>
            {types.map((type) => (
                <button key={type} type="button" role="tab" aria-selected={activeType === type} onClick={() => onChange(type)}>
                    <FontAwesomeIcon icon={TAB_LABELS[type].icon}/> {labels?.[type] ?? TAB_LABELS[type].label}
                    {counts?.[type] !== undefined && <span>{counts[type]}</span>}
                </button>
            ))}
        </div>
    )
}
