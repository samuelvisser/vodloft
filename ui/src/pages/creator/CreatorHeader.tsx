import type {ReactNode} from 'react'
import {toImageUrl} from '../../components/Episode/EpisodeCard'

type CreatorHeaderProps = {
    title: string
    /** What the Site calls it, such as "YouTube creator". */
    label: string
    handle?: string | null
    avatarUrl?: string | null
    bannerUrl?: string | null
    facts?: string[]
    description?: string | null
    url?: string | null
    /** The id of the title, when it is the page's own heading. */
    titleId?: string
    actions?: ReactNode
}

/** A creator's banner, picture, name and facts, as its Site shows them. */
export default function CreatorHeader({title, label, handle, avatarUrl, bannerUrl, facts = [], description, url, titleId, actions}: CreatorHeaderProps) {
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
                        {url && <> · <a href={url} target="_blank" rel="noreferrer">Open on the site</a></>}
                    </p>
                    {description && <p className="creator-description">{description}</p>}
                </div>
                {actions && <div className="creator-actions">{actions}</div>}
            </div>
        </header>
    )
}
