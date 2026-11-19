import {Link} from 'react-router-dom'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import {toImageUrl} from '../Episode/EpisodeCard'
import './CreatorLink.css'

type CreatorLinkProps = {
    slug: string
    title: string
    avatarUrl?: string | null
}

/** The creator a collection belongs to: their picture and name, with a chevron that says it opens their page. */
export default function CreatorLink({slug, title, avatarUrl}: CreatorLinkProps) {
    const avatar = toImageUrl(avatarUrl)
    return (
        <Link className="creator-link" to={`/creator/${slug}`}>
            {avatar
                ? <img className="creator-link-avatar" src={avatar} alt="" loading="lazy"/>
                : <span className="creator-link-avatar creator-link-avatar--empty" aria-hidden="true">{title.slice(0, 2).toUpperCase()}</span>}
            <span className="creator-link-name">{title}</span>
            <FontAwesomeIcon icon={faIcon('fass', 'chevron-right')} className="creator-link-chevron" aria-hidden="true"/>
        </Link>
    )
}
