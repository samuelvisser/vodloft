import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import './DrmProtected.css'

type Lockable = {
    access?: string | null
    accessLabel?: string | null
    accessDescription?: string | null
    accessLocked?: boolean
    accessGranted?: boolean
    accessCheckAt?: Date | string | null
}

function checkDate(value: Date | string): string {
    return new Date(value).toLocaleDateString(undefined, {month: 'short', day: 'numeric'})
}

/** Marks an episode or video the Source only gives with an access, such as a channel membership or NPO Plus.
 * The lock is open when VODLoft has that access, such as through the account it signs in with.
 * As text, it is a label on a details line instead of a pill. */
export function AccessBadge({label, description, granted = false, onCover = false, asText = false}: {label?: string | null, description?: string | null, granted?: boolean, onCover?: boolean, asText?: boolean}) {
    const name = label ?? 'Locked'
    const title = granted
        ? `${name}: your account has this, so VODLoft can download it`
        : description ?? `${name}: VODLoft cannot download this without it`
    return (
        <span className={asText ? 'episode-summary-item episode-summary-label access-label' : `drm-badge access-badge${onCover ? ' drm-badge-cover' : ''}`} title={title}>
            <FontAwesomeIcon icon={faIcon('fass', granted ? 'lock-open' : 'lock')} aria-hidden="true"/>
            {name}
        </span>
    )
}

/** The badge, only for media that needs an access. */
export function ItemAccessBadge({item, onCover = false, asText = false}: {item: Lockable, onCover?: boolean, asText?: boolean}) {
    return item.access ? <AccessBadge label={item.accessLabel} description={item.accessDescription} granted={item.accessGranted} onCover={onCover} asText={asText}/> : null
}

/** Takes the place of the download controls for locked media. */
export function AccessNotice({item}: {item: Lockable}) {
    const check = item.accessCheckAt
        ? ` VODLoft checks again on ${checkDate(item.accessCheckAt)} in case it opens up for everyone.`
        : ''
    return (
        <div className="drm-notice access-notice" role="status">
            <FontAwesomeIcon icon={faIcon('fass', 'lock')} aria-hidden="true"/>
            <span>{item.accessDescription ?? 'Only members or subscribers can watch this.'} VODLoft cannot download it.{check}</span>
        </div>
    )
}
