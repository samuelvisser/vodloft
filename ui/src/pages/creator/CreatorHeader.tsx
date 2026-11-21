import {useLayoutEffect, useRef, useState, type ReactNode, type Ref} from 'react'
import {toImageUrl} from '../../components/Episode/EpisodeCard'
import {capitalized} from '../../types/creator'
import LinkedText from '../../components/common/LinkedText'

type CreatorHeaderProps = {
    title: string
    /** What it is, such as "YouTube creator", or "creator" on several Sites. */
    label: string
    handle?: string | null
    avatarUrl?: string | null
    bannerUrl?: string | null
    facts?: string[]
    description?: string | null
    /** The id of the title, when it is the page's own heading. */
    titleId?: string
    actions?: ReactNode
    /** The row of buttons, for a page that measures whether they fit. */
    actionsRef?: Ref<HTMLDivElement>
    /** A row of figures under the description, such as how many collections the creator has. */
    stats?: ReactNode
}

/** The description, two lines of it until the user asks for more. */
function CreatorDescription({text}: {text: string}) {
    const ref = useRef<HTMLParagraphElement>(null)
    const [open, setOpen] = useState(false)
    const [cut, setCut] = useState(false)
    useLayoutEffect(() => {
        const element = ref.current
        if (!element || open) return
        const measure = () => setCut(element.scrollHeight > element.clientHeight + 1)
        measure()
        const observer = new ResizeObserver(measure)
        observer.observe(element)
        return () => observer.disconnect()
    }, [text, open])
    return (
        <div className={`creator-description-wrap${cut && !open ? ' is-cut' : ''}`}>
            <p ref={ref} className={`creator-description${open ? ' is-open' : ''}`}><LinkedText text={text}/></p>
            {/* Cut, Read more sits at the end of the second line, as on YouTube; open, Show less follows the text. */}
            {(cut || open) && (
                <button type="button" className="creator-description-toggle" onClick={() => setOpen(!open)} aria-expanded={open}>
                    {!open && <span aria-hidden="true">… </span>}
                    <span className="read-more-toggle">{open ? 'Show less' : 'Read more'}</span>
                </button>
            )}
        </div>
    )
}

/** A creator's banner with their picture over it, their name, what their Site says about them, and their buttons. */
export default function CreatorHeader({title, label, handle, avatarUrl, bannerUrl, facts = [], description, titleId, actions, actionsRef, stats}: CreatorHeaderProps) {
    const Heading = titleId ? 'h1' : 'h2'
    const banner = toImageUrl(bannerUrl)
    const avatar = toImageUrl(avatarUrl)
    return (
        <header className={`creator-header${banner ? '' : ' creator-header--no-banner'}`}>
            {banner && <div className="creator-banner" style={{backgroundImage: `url("${banner}")`}} aria-hidden="true"/>}
            {avatar
                ? <img className="creator-avatar" src={avatar} alt="" loading="lazy"/>
                : <span className="creator-avatar creator-avatar--empty" aria-hidden="true">{title.slice(0, 1)}</span>}
            <Heading id={titleId} className="creator-name">{title}</Heading>
            {actions && <div ref={actionsRef} className="creator-actions">{actions}</div>}
            <div className="creator-about">
                {/* Each fact stays whole, such as "1.7M subscribers": a line breaks only between them. The label can break
                    anywhere, since it names every Site of a creator on several, such as "Creator on YouTube, SoundCloud and
                    Twitch". */}
                <p className="creator-facts">
                    {[capitalized(label), ...[handle, ...facts].filter(Boolean).map((fact) => fact!.replace(/ /g, '\u00a0'))].join('\u00a0· ')}
                </p>
                {description && <CreatorDescription text={description}/>}
                {stats}
            </div>
        </header>
    )
}
