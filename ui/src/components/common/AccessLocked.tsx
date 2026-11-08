import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import './DrmProtected.css'

type Lockable = {
    access?: string | null
    accessLabel?: string | null
    accessDescription?: string | null
    accessLocked?: boolean
    accessCheckAt?: Date | string | null
}

function checkDate(value: Date | string): string {
    return new Date(value).toLocaleDateString(undefined, {month: 'short', day: 'numeric'})
}

/** Marks an episode or video the Source only gives with an access, such as a channel membership or NPO Plus. */
export function AccessBadge({label, description, onCover = false}: {label?: string | null, description?: string | null, onCover?: boolean}) {
    const name = label ?? 'Locked'
    return (
        <span className={`drm-badge access-badge${onCover ? ' drm-badge-cover' : ''}`} title={description ?? `${name}: VODLoft cannot download this without it`}>
            <FontAwesomeIcon icon={faIcon('fass', 'lock')} aria-hidden="true"/>
            {name}
        </span>
    )
}

/** The badge, only for media that needs an access. */
export function ItemAccessBadge({item, onCover = false}: {item: Lockable, onCover?: boolean}) {
    return item.access ? <AccessBadge label={item.accessLabel} description={item.accessDescription} onCover={onCover}/> : null
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
