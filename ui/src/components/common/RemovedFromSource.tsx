import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import './DrmProtected.css'

export const REMOVED_FROM_SOURCE_MESSAGE = 'No longer available at the Source; Home asks whether to keep its downloads'

/** Marks an episode the Source no longer has, such as a deleted or private video; as text, a label on a details line. */
export function RemovedBadge({onCover = false, asText = false}: {onCover?: boolean, asText?: boolean}) {
    return (
        <span className={asText ? 'episode-summary-item episode-summary-label removed-label' : `drm-badge removed-badge${onCover ? ' drm-badge-cover' : ''}`} title={REMOVED_FROM_SOURCE_MESSAGE}>
            <FontAwesomeIcon icon={faIcon('fass', 'link-slash')} aria-hidden="true"/>
            Removed
        </span>
    )
}

/** Marks media its Site removed itself, as the Site removes all its media after a while, such as Twitch its past
 *  broadcasts: it expired there. VODLoft expected it to go, so it is not missing; as text, a label on a details line. */
export function ExpiredBadge({removedBy}: {removedBy: {siteName: string, retention: string}}) {
    return (
        <span
            className="episode-summary-item episode-summary-label removed-label"
            title={`${removedBy.retention} Your downloads stay, but ${removedBy.siteName} no longer offers it.`}
        >
            <FontAwesomeIcon icon={faIcon('fass', 'clock-rotate-left')} aria-hidden="true"/>
            Expired on {removedBy.siteName}
        </span>
    )
}
