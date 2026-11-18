import type {ReactNode} from 'react'
import {toImageUrl} from '../../components/Episode/EpisodeCard'

type CreatorHeaderProps = {
    title: string
    /** What it is, such as "YouTube creator", or "creator" on several Sites. */
    label: string
    handle?: string | null
    avatarUrl?: string | null
    bannerUrl?: string | null
    facts?: string[]
    description?: string | null
    /** Its pages on its Sites, such as "Open on YouTube". */
    links?: {label: string, url: string}[]
    /** The id of the title, when it is the page's own heading. */
    titleId?: string
    actions?: ReactNode
}

/** A creator's banner, picture, name and facts, as their Site shows them, and their pages on their Sites. */
export default function CreatorHeader({title, label, handle, avatarUrl, bannerUrl, facts = [], description, links = [], titleId, actions}: CreatorHeaderProps) {
    const Heading = titleId ? 'h1' : 'h2'
    const banner = toImageUrl(bannerUrl)
    const avatar = toImageUrl(avatarUrl)
    return (
        <header className="creator-header">
            {banner && <div className="creator-banner" style={{backgroundImage: `url("${banner}")`}} aria-hidden="true"/>}
            <div className="creator-identity">
                {avatar
                    ? <img className="creator-avatar" src={avatar} alt="" loading="lazy"/>
                    : <span className="creator-avatar creator-avatar--empty" aria-hidden="true">{title.slice(0, 1)}</span>}
                <div className="creator-identity-copy">
                    <span className="creator-kind">{label}</span>
                    <Heading id={titleId}>{title}</Heading>
                    <p className="creator-facts">
                        {[handle, ...facts].filter(Boolean).join(' · ')}
                        {links.map((link) => (
                            <span key={link.url}> · <a href={link.url} target="_blank" rel="noreferrer">{link.label}</a></span>
                        ))}
                    </p>
                    {description && <p className="creator-description">{description}</p>}
                </div>
                {actions && <div className="creator-actions">{actions}</div>}
            </div>
        </header>
    )
}
