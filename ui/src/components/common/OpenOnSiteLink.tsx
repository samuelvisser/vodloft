import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import SiteIcon, {type SiteIconSite} from './SiteIcon'
import './OpenOnSiteLink.css'

type OpenOnSiteLinkProps = {
    url: string
    /** The site's name, such as YouTube. */
    siteName: string
    /** The site's icon (or its globe and initials), shown instead of the open-elsewhere arrow. */
    site?: SiteIconSite
    /** Shows only the icon, where the site's name does not fit. */
    iconOnly?: boolean
    className?: string
}

/** A button that opens something on its own site, such as "Open on YouTube"; a phone shows just the site's name. */
export default function OpenOnSiteLink({url, siteName, site, iconOnly = false, className}: OpenOnSiteLinkProps) {
    return (
        <a
            className={`btn open-on-site${iconOnly ? ' open-on-site--icon' : ''}${className ? ` ${className}` : ''}`}
            href={url} target="_blank" rel="noreferrer" title={`Open on ${siteName}`}
            aria-label={iconOnly ? `Open on ${siteName}` : undefined}
        >
            {site ? <SiteIcon site={site}/> : <FontAwesomeIcon icon={faIcon('fass', 'arrow-up-right-from-square')} aria-hidden="true"/>}
            {!iconOnly && <span className="open-on-site-label"><span className="open-on-site-prefix">Open on </span>{siteName}</span>}
        </a>
    )
}
