import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {Link} from 'react-router-dom'
import {faIcon} from '../../../icons/faIcon'
import './Breadcrumb.css'

export type BreadcrumbItem = {
    label: string
    to: string
}

type BreadcrumbProps = {
    items: BreadcrumbItem[]
    className?: string
}

/**
 * The trail above a page that shows where it sits, such as Library > a collection. Every step links to its page, and a
 * long last step is cut short instead of taking a second line.
 */
export default function Breadcrumb({items, className}: BreadcrumbProps) {
    return (
        <nav className={['breadcrumb', className].filter(Boolean).join(' ')} aria-label="Breadcrumb">
            {items.map((item, index) => (
                <span key={item.to} className="breadcrumb-step">
                    {index > 0 && <FontAwesomeIcon icon={faIcon('fass', 'chevron-right')} aria-hidden="true"/>}
                    <Link className="quiet-link" to={item.to}>{item.label}</Link>
                </span>
            ))}
        </nav>
    )
}
