import type {ReactNode} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import './LoadingNote.css'

/** The one way VODLoft says it is still waiting for something: a spinner beside what it waits for. */
export default function LoadingNote({children, className}: {children: ReactNode; className?: string}) {
    return (
        <p className={className ? `loading-note ${className}` : 'loading-note'} role="status">
            <FontAwesomeIcon icon={faIcon('fass', 'spinner')} spin aria-hidden="true"/>
            {children}
        </p>
    )
}
