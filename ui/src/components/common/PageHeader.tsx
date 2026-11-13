import {useState, type ReactNode} from 'react'
import type {IconProp} from '@fortawesome/fontawesome-svg-core'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {Link} from 'react-router-dom'
import './PageHeader.css'

type PageHeaderProps = {
    title: ReactNode
    /** The h1's id, for the page section's aria-labelledby. */
    titleId: string
    /** A line under the title, such as a PageSubtitle or a view-description paragraph. */
    subtitle?: ReactNode
    /** The page's buttons, each a PageHeaderAction. */
    actions?: ReactNode
    /** A row under the title, such as the Library's media type tabs. */
    children?: ReactNode
    className?: string
}

/**
 * A page's title with its action buttons on the right. The buttons always stay on one row beside the title: when the
 * header is too narrow for their words, they all become round icon buttons.
 */
export default function PageHeader({title, titleId, subtitle, actions, children, className}: PageHeaderProps) {
    return (
        <div className={['page-header', className].filter(Boolean).join(' ')}>
            <h1 id={titleId}>{title}</h1>
            {subtitle && <div className="page-header-subtitle">{subtitle}</div>}
            {actions && <div className="page-header-actions">{actions}</div>}
            {children && <div className="page-header-below">{children}</div>}
        </div>
    )
}

type PageHeaderActionProps = {
    icon: IconProp
    /** The button's words: shown when there is room, otherwise kept for screen readers and as a tooltip. */
    label: string
    variant?: 'primary' | 'secondary'
    /** Keep the words while the header has room for them, after the other buttons have become icons. */
    keepLabel?: boolean
    /** For a button that switches something on and off: whether it is on. Switching plays a short swap animation. */
    toggled?: boolean
} & ({to: string, onClick?: never} | {onClick: () => void, to?: never})

/** A button in a PageHeader: a link with `to`, or a button with `onClick`. */
export function PageHeaderAction({icon, label, variant = 'primary', keepLabel, toggled, to, onClick}: PageHeaderActionProps) {
    // A toggle animates only once it has been switched, not when the page first shows it.
    const [firstToggled, setFirstToggled] = useState(toggled)
    const [switched, setSwitched] = useState(false)
    if (toggled !== firstToggled && !switched) {
        setFirstToggled(toggled)
        setSwitched(true)
    }
    const className = [
        `btn btn-${variant} page-header-action`,
        keepLabel && 'keeps-label',
        switched && 'is-switching',
    ].filter(Boolean).join(' ')
    // The key makes the icon and words new elements on each switch, so their entrance animation plays again.
    const content = (
        <>
            <FontAwesomeIcon key={`icon-${toggled}`} icon={icon} aria-hidden="true" className="page-header-action-icon"/>
            <span key={`label-${toggled}`} className="page-header-action-label">{label}</span>
        </>
    )
    if (to !== undefined) return <Link className={className} to={to} title={label}>{content}</Link>
    return <button type="button" className={className} onClick={onClick} title={label}>{content}</button>
}
