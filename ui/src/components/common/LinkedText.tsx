import {Fragment} from 'react'
import {Link} from 'react-router-dom'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import {splitTextLinks} from '../../utils/textLinks'
import {can} from '../../lib/access'
import './LinkedText.css'

// The address, then the open-link icon. The icon stays on the line of the address's last character, and is not underlined.
const label = (url: string) => (
    <>
        {url.slice(0, -1)}
        <span className="text-link-end">
            {url.slice(-1)}
            <span className="text-link-icon"><FontAwesomeIcon icon={faIcon('fass', 'arrow-up-right-from-square')} aria-hidden="true"/></span>
        </span>
    </>
)

/**
 * Text, such as a description, whose web addresses are links. A link opens the address on the Add media page,
 * which looks it up, so whatever it points to can be added right away. A user who cannot add media opens the
 * address itself instead.
 */
export default function LinkedText({text}: {text: string}) {
    const lookUp = can('add_media')
    return (
        <>
            {splitTextLinks(text).map((part, index) => part.kind === 'text'
                ? <Fragment key={index}>{part.text}</Fragment>
                : lookUp
                    ? <Link key={index} className="text-link" to={`/add?url=${encodeURIComponent(part.url)}`} title="Look up this link">{label(part.url)}</Link>
                    : <a key={index} className="text-link" href={part.url} target="_blank" rel="noreferrer">{label(part.url)}</a>)}
        </>
    )
}
