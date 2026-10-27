import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import './DrmProtected.css'

export const REMOVED_FROM_SOURCE_MESSAGE = 'No longer available at the Source; downloaded files are kept'

/** Marks an episode the Source no longer has, such as a deleted or private video. */
export function RemovedBadge({onCover = false}: {onCover?: boolean}) {
    return (
        <span className={`drm-badge removed-badge${onCover ? ' drm-badge-cover' : ''}`} title={REMOVED_FROM_SOURCE_MESSAGE}>
            <FontAwesomeIcon icon={faIcon('fass', 'link-slash')} aria-hidden="true"/>
            Removed
        </span>
    )
}
