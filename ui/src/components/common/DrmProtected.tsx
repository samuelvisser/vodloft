import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import './DrmProtected.css'

export const DRM_PROTECTED_MESSAGE = 'Protected by DRM, cannot be downloaded'

/** What the DRM badge and notice say in a collection whose own yt-dlp options allow unplayable formats. */
const DRM_UNPLAYABLE_MESSAGE = 'Protected by DRM. Encrypted files might be able to download depending on the yt-dlp extractor for this site. However, these files are not playable.'

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
            <FontAwesomeIcon icon={faIcon('fass', unplayableAllowed ? 'lock-open' : 'lock')} aria-hidden="true"/>
            DRM
        </span>
    )
}

/**
 * Takes the place of the download controls for media protected by DRM. With unplayableAllowed, its collection lets
 * yt-dlp try to download it anyway, and the notice stands above the download controls instead.
 */
export function DrmNotice({unplayableAllowed = false}: {unplayableAllowed?: boolean}) {
    return (
        <div className="drm-notice" role="status">
            <FontAwesomeIcon icon={faIcon('fass', unplayableAllowed ? 'lock-open' : 'lock')} aria-hidden="true"/>
            <span>{unplayableAllowed ? DRM_UNPLAYABLE_MESSAGE : `${DRM_PROTECTED_MESSAGE}.`}</span>
        </div>
    )
}
