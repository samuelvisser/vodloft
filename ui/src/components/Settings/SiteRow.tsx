import {useState, type ReactNode} from 'react'

import './SiteSettingsCard.css'

export type SiteBadgeTone = 'own' | 'on' | 'off' | 'problem'

/** A short state shown next to a Site's name, such as "Own schedule" or "Cookies file". */
export function SiteBadge({tone, children}: {tone: SiteBadgeTone; children: string}) {
    return <span className={`site-settings-badge site-settings-badge--${tone}`}>{children}</span>
}

/** The list the Sites of one settings card stack in. */
export function SiteRows({className, children}: {className?: string; children: ReactNode}) {
    return <div className={['site-settings-sites', className].filter(Boolean).join(' ')}>{children}</div>
}

/** One Site in a card of per-Site settings: its name, domains and badges, opened to show its body.
 *  ``forceOpen`` keeps it open, such as while one of its settings shows an error. */
export default function SiteRow({name, domains, badges, forceOpen = false, bodyClassName, children}: {
    name: string
    domains: readonly string[]
    badges: ReactNode
    forceOpen?: boolean
    bodyClassName?: string
    children: ReactNode
}) {
    const [open, setOpen] = useState(false)
    return (
        <details className="site-settings-site" open={open || forceOpen} onToggle={(event) => setOpen(event.currentTarget.open)}>
            <summary>
                <span className="site-settings-site__name">
                    <strong>{name}</strong>
                    {domains.length ? <span>{domains.join(', ')}</span> : null}
                </span>
                <span className="site-settings-site__badges">{badges}</span>
            </summary>
            <div className={['site-settings-site__body', bodyClassName].filter(Boolean).join(' ')}>{children}</div>
        </details>
    )
}
