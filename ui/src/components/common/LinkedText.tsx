import {Fragment, useMemo} from 'react'
import {Link} from 'react-router-dom'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import {splitTextLinks} from '../../utils/textLinks'
import {useMediaLinks, useWorkingMediaLinks} from '../../lib/queries'
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
 * Text, such as a description, whose links to media are links to the Add media page, which looks the link up so
 * whatever it points to can be added right away. Only a link on a Site VODLoft knows for media can become one, and
 * only for a user who can add media; any other address stays text. Such a link becomes one once the check that Add
 * media finds something there is in, which runs after the text has shown, so the page never waits for it.
 */
export default function LinkedText({text}: {text: string}) {
    const parts = useMemo(() => splitTextLinks(text), [text])
    const urls = useMemo(() => [...new Set(parts.flatMap((part) => part.kind === 'link' ? [part.url] : []))].sort(), [parts])
    const {data: media} = useMediaLinks(urls)
    const known = useMemo(() => urls.filter((url) => media?.has(url)), [urls, media])
    const working = useWorkingMediaLinks(known)
    return (
        <>
            {parts.map((part, index) => part.kind === 'link' && working.has(part.url)
                ? <Link key={index} className="text-link" to={`/add?url=${encodeURIComponent(part.url)}`} title="Look up this link">{label(part.url)}</Link>
                : <Fragment key={index}>{part.kind === 'link' ? part.url : part.text}</Fragment>)}
        </>
    )
}
