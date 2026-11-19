import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import './OpenOnSiteLink.css'

type OpenOnSiteLinkProps = {
    url: string
    /** The site's name, such as YouTube. */
    siteName: string
    className?: string
}

/** A button that opens something on its own site, such as "Open on YouTube"; a phone shows just the site's name. */
export default function OpenOnSiteLink({url, siteName, className}: OpenOnSiteLinkProps) {
    return (
        <a className={`btn open-on-site${className ? ` ${className}` : ''}`} href={url} target="_blank" rel="noreferrer" title={`Open on ${siteName}`}>
            <FontAwesomeIcon icon={faIcon('fass', 'arrow-up-right-from-square')} aria-hidden="true"/>
            <span className="open-on-site-label"><span className="open-on-site-prefix">Open on </span>{siteName}</span>
        </a>
    )
}
