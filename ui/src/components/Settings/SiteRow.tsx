import {useState, type MouseEvent, type ReactNode} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'

import ConfirmDialog from '../ConfirmDialog/ConfirmDialog'
import {faIcon} from '../../icons/faIcon'
import {useRemoveSite} from '../../lib/queries'
import toast from '../../lib/toast'
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

/** The trash button of an opened Site that has nothing in VODLoft, which removes the Site after asking. */
function RemoveSiteButton({siteKey, name}: {siteKey: string; name: string}) {
    const removeSite = useRemoveSite()
    const [asking, setAsking] = useState(false)
    const ask = (event: MouseEvent) => {
        // The button sits in the row's header, which opens and closes the row on a click.
        event.preventDefault()
        event.stopPropagation()
        setAsking(true)
    }
    const remove = async () => {
        try {
            await removeSite(siteKey)
            toast.success(`${name} removed`)
            setAsking(false)
        } catch (error) {
            toast.error((error as Error).message)
        }
    }
    return (
        <>
            <button
                type="button" className="btn btn-secondary site-settings-site__remove" aria-label={`Remove ${name}`}
                title={`Remove ${name}`} onClick={ask}
            >
                <FontAwesomeIcon icon={faIcon('fass', 'trash')} aria-hidden="true"/>
            </button>
            {asking ? (
                <ConfirmDialog
                    open
                    title={`Remove ${name}?`}
                    icon={faIcon('fass', 'trash')}
                    iconTone="danger"
                    onDismiss={() => setAsking(false)}
                    confirmButton={{label: 'Remove', className: 'btn-danger', onClick: remove}}
                >
                    <p>
                        VODLoft has nothing from {name}, so it leaves every list of sites, with its cookies file.
                        Add it again, or add something from it, to bring it back with everything VODLoft offers
                        there and the settings it had.
                    </p>
                </ConfirmDialog>
            ) : null}
        </>
    )
}

/** One Site in a card of per-Site settings: its name, domains and badges, opened to show its body.
 *  ``forceOpen`` keeps it open, such as while one of its settings shows an error. The ``alone`` Site of a card
 *  that lists only one is always open, with nothing to fold. An opened ``removable`` Site, one with nothing in
 *  VODLoft, has a trash button in its header. */
export default function SiteRow({siteKey, name, domains, badges, removable = false, forceOpen = false, alone = false, bodyClassName, children}: {
    siteKey: string
    name: string
    domains: readonly string[]
    badges: ReactNode
    removable?: boolean
    forceOpen?: boolean
    alone?: boolean
    bodyClassName?: string
    children: ReactNode
}) {
    const [open, setOpen] = useState(false)
    const shown = open || forceOpen || alone
    return (
        <details
            className={[
                'site-settings-site', shown && removable ? 'site-settings-site--removable' : null,
                alone ? 'site-settings-site--alone' : null,
            ].filter(Boolean).join(' ')}
            open={shown} onToggle={(event) => setOpen(event.currentTarget.open)}>
            <summary onClick={alone ? (event) => event.preventDefault() : undefined}>
                <span className="site-settings-site__name">
                    <strong>{name}</strong>
                    {domains.length ? <span>{domains.join(', ')}</span> : null}
                </span>
                <span className="site-settings-site__badges">{badges}</span>
                {shown && removable ? <RemoveSiteButton siteKey={siteKey} name={name}/> : null}
            </summary>
            <div className={['site-settings-site__body', bodyClassName].filter(Boolean).join(' ')}>{children}</div>
        </details>
    )
}
