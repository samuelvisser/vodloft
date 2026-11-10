import type {ReactNode} from 'react'

import './SelectAllLabel.css'

/** A multi-select's label with a Select all button beside it, which is off when everything is already chosen. */
export default function SelectAllLabel({htmlFor, children, allChosen, onSelectAll}: {
    htmlFor: string
    children: ReactNode
    allChosen: boolean
    onSelectAll: () => void
}) {
    return (
        <div className="select-all-label">
            <label htmlFor={htmlFor}>{children}</label>
            <button type="button" className="btn btn-link" disabled={allChosen} onClick={onSelectAll}>
                Select all
            </button>
        </div>
    )
}
