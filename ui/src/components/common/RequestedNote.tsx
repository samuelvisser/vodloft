import type {ReactNode} from 'react'
import './RequestedNote.css'

/** A small advisory under a field that a link filled in, once its value no longer gives what the link asked for. */
export default function RequestedNote({children}: {children: ReactNode}) {
    return <div className="requested-note" role="status">{children}</div>
}
