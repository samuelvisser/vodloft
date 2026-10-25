import type {IconProp} from '@fortawesome/fontawesome-svg-core'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'

export type MediaType = 'shows' | 'movies' | 'videos'

const TAB_LABELS: Record<MediaType, {label: string; icon: IconProp}> = {
    shows: {label: 'Shows', icon: faIcon('fass', 'tv')},
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
}

export default function MediaTypeTabs({
    activeType,
    onChange,
    ariaLabel,
    types = ['shows', 'movies'],
    counts,
}: MediaTypeTabsProps) {
    return (
        <div className="media-type-tabs browse-type-tabs" role="tablist" aria-label={ariaLabel}>
            {types.map((type) => (
                <button key={type} type="button" role="tab" aria-selected={activeType === type} onClick={() => onChange(type)}>
                    <FontAwesomeIcon icon={TAB_LABELS[type].icon}/> {TAB_LABELS[type].label}
                    {counts?.[type] !== undefined && <span>{counts[type]}</span>}
                </button>
            ))}
        </div>
    )
}
