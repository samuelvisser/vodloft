import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import {siteIcon} from '../../icons/siteIcons'
import './SiteIcon.css'

export type SiteIconSite = {
    /** The Site's Font Awesome icon as prefix:name, such as fab:youtube. */
    icon?: string | null
    /** The Site's name in at most two letters, such as YT. */
    initials: string
}

/** A Site's own icon, or, for a Site without one, a globe with the Site's initials beside it. */
export default function SiteIcon({site}: {site: SiteIconSite}) {
    const icon = siteIcon(site.icon)
    if (icon) return <FontAwesomeIcon className="site-icon" icon={icon} aria-hidden="true"/>
    return (
        <span className="site-icon site-icon--initials" aria-hidden="true">
            <FontAwesomeIcon icon={faIcon('fass', 'globe')}/>
            <span className="site-icon-initials">{site.initials}</span>
        </span>
    )
}
