import type {ReactNode} from 'react'
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
} & ({to: string, onClick?: never} | {onClick: () => void, to?: never})

/** A button in a PageHeader: a link with `to`, or a button with `onClick`. */
export function PageHeaderAction({icon, label, variant = 'primary', to, onClick}: PageHeaderActionProps) {
    const className = `btn btn-${variant} page-header-action`
    const content = (
        <>
            <FontAwesomeIcon icon={icon} aria-hidden="true"/>
            <span className="page-header-action-label">{label}</span>
        </>
    )
    if (to !== undefined) return <Link className={className} to={to} title={label}>{content}</Link>
    return <button type="button" className={className} onClick={onClick} title={label}>{content}</button>
}
