import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import {useSourceLookup} from '../../lib/queries'
import './DrmProtected.css'

/** What the Source calls the subscription, such as NPO Plus. */
function useSubscriptionName(sourceKey?: string | null): string {
    return useSourceLookup().get(sourceKey)?.subscriptionName ?? 'Subscription'
}

export function needsSubscriptionMessage(name: string): string {
    return `Needs ${name}, cannot be downloaded`
}

/** Marks an episode or video that the Source only gives to paying subscribers. */
export function SubscriptionBadge({sourceKey, onCover = false}: {sourceKey?: string | null, onCover?: boolean}) {
    const name = useSubscriptionName(sourceKey)
    return (
        <span className={`drm-badge subscription-badge${onCover ? ' drm-badge-cover' : ''}`} title={needsSubscriptionMessage(name)}>
            <FontAwesomeIcon icon={faIcon('fass', 'star')} aria-hidden="true"/>
            {name}
        </span>
    )
}

/** Takes the place of the download controls for media that needs a subscription. */
export function SubscriptionNotice({sourceKey}: {sourceKey?: string | null}) {
    const name = useSubscriptionName(sourceKey)
    return (
        <div className="drm-notice subscription-notice" role="status">
            <FontAwesomeIcon icon={faIcon('fass', 'star')} aria-hidden="true"/>
            <span>Only {name} subscribers can watch this, so VODLoft cannot download it yet.</span>
        </div>
    )
}
