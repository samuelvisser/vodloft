import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import './DrmProtected.css'

export const DRM_PROTECTED_MESSAGE = 'Protected by DRM, cannot be downloaded'

/** What the DRM badge says in a collection whose own yt-dlp options allow unplayable formats. */
const DRM_UNPLAYABLE_MESSAGE = 'Protected by DRM; this collection’s yt-dlp options allow unplayable formats, so yt-dlp tries to download it'

/**
 * Marks an episode, movie or video that is protected by DRM; as text, a label on a details line instead of a pill.
 * With unplayableAllowed, its collection lets yt-dlp try to download it anyway.
 */
export function DrmBadge({onCover = false, asText = false, unplayableAllowed = false}: {onCover?: boolean, asText?: boolean, unplayableAllowed?: boolean}) {
    return (
        <span
            className={asText ? 'episode-summary-item episode-summary-label drm-label' : `drm-badge${onCover ? ' drm-badge-cover' : ''}`}
            title={unplayableAllowed ? DRM_UNPLAYABLE_MESSAGE : DRM_PROTECTED_MESSAGE}
        >
            <FontAwesomeIcon icon={faIcon('fass', 'lock')} aria-hidden="true"/>
            DRM
        </span>
    )
}

/** Takes the place of the download controls for media protected by DRM. */
export function DrmNotice() {
    return (
        <div className="drm-notice" role="status">
            <FontAwesomeIcon icon={faIcon('fass', 'lock')} aria-hidden="true"/>
            <span>{DRM_PROTECTED_MESSAGE}.</span>
        </div>
    )
}
