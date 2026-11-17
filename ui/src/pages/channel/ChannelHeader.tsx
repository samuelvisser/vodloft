import type {ReactNode} from 'react'
import {toImageUrl} from '../../components/Episode/EpisodeCard'

type ChannelHeaderProps = {
    title: string
    /** What the Site calls it, such as "YouTube channel". */
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

/** A channel's banner, picture, name and facts, as its Site shows them. */
export default function ChannelHeader({title, label, handle, avatarUrl, bannerUrl, facts = [], description, url, titleId, actions}: ChannelHeaderProps) {
    const Heading = titleId ? 'h1' : 'h2'
    const banner = toImageUrl(bannerUrl)
    const avatar = toImageUrl(avatarUrl)
    return (
        <header className="channel-header">
            {banner && <div className="channel-banner" style={{backgroundImage: `url("${banner}")`}} aria-hidden="true"/>}
            <div className="channel-identity">
                {avatar
                    ? <img className="channel-avatar" src={avatar} alt="" loading="lazy"/>
                    : <span className="channel-avatar channel-avatar--empty" aria-hidden="true">{title.slice(0, 1)}</span>}
                <div className="channel-identity-copy">
                    <span className="channel-kind">{label}</span>
                    <Heading id={titleId}>{title}</Heading>
                    <p className="channel-facts">
                        {[handle, ...facts].filter(Boolean).join(' · ')}
                        {url && <> · <a href={url} target="_blank" rel="noreferrer">Open on the site</a></>}
                    </p>
                    {description && <p className="channel-description">{description}</p>}
                </div>
                {actions && <div className="channel-actions">{actions}</div>}
            </div>
        </header>
    )
}
