import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import {siteIcon} from '../../icons/siteIcons'
import SiteIcon, {type SiteIconSite} from './SiteIcon'
import './SiteLink.css'

type SiteLinkProps = {
    /** The page on the site, such as a channel or a video. */
    url: string
    /** The site's name, such as YouTube. */
    siteName: string
    /** The site's icon and initials, when VODLoft knows the site. */
    site?: SiteIconSite | null
    /** Only the site's icon, or a globe with its initials, where its name does not fit. */
    compact?: boolean
    className?: string
}

/**
 * The button that opens something on its own site, wherever VODLoft links out to one: the site's icon and "Open on
 * YouTube", or just "YouTube" on a phone, with the open-elsewhere arrow for a site without an icon. Compact, it shows
 * only the site's icon, or a globe with the site's initials.
 */
export default function SiteLink({url, siteName, site, compact = false, className}: SiteLinkProps) {
    const icon = siteIcon(site?.icon)
    return (
        <a
            className={`btn site-link${compact ? ' site-link--compact' : ''}${className ? ` ${className}` : ''}`}
            href={url} target="_blank" rel="noreferrer" title={`Open on ${siteName}`}
            aria-label={compact ? `Open on ${siteName}` : undefined}
        >
            {compact && site
                ? <SiteIcon site={site}/>
                : <FontAwesomeIcon icon={icon ?? faIcon('fass', 'arrow-up-right-from-square')} aria-hidden="true"/>}
            {!compact && <span className="site-link-label"><span className="site-link-prefix">Open on </span>{siteName}</span>}
        </a>
    )
}
