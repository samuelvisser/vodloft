import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import type {BulkResult} from '../../types/schemas/profile_bulk'
import {countOf} from './bulkApi'
import type {BulkSelection} from './useBulkSelection'
import './ProfileBulkEdit.css'

/** Turns bulk edit on beside a table's Add button, and becomes Done while it is on. */
export function BulkEditButton({selection}: {selection: BulkSelection}) {
    if (selection.active) {
        return <button type="button" className="btn btn-primary bulk-edit-toggle" onClick={selection.stop}>Done</button>
    }
    return (
        <button type="button" className="btn btn-secondary bulk-edit-toggle" onClick={selection.start}>
            <FontAwesomeIcon icon={faIcon('fass', 'list-check')} aria-hidden="true"/>
            Bulk edit
        </button>
    )
}

/** Select all, beside the filters' count: it takes every profile the filters match, loaded or not. */
export function SelectAll({selection, filtered}: {selection: BulkSelection, filtered: boolean}) {
    if (!selection.active) return null
    const count = selection.matchingCount
    const all = selection.allState === 'all'
    return (
        <label className="bulk-select-all">
            <input
                type="checkbox"
                className="bulk-check"
                checked={all}
                disabled={!count}
                ref={(element) => { if (element) element.indeterminate = selection.allState === 'some' }}
                onChange={selection.toggleAll}
            />
            <span>{all ? 'Deselect all' : 'Select all'}{filtered && count ? ` ${count.toLocaleString()} matching` : ''}</span>
        </label>
    )
}

type BulkActionBarProps = {
    selection: BulkSelection
    noun: [string, string]
    busy: boolean
    /** Enable and Disable, for tables whose profiles can be switched off. */
    onEnable?: (enable: boolean) => void
    onChange: () => void
    onDelete: () => void
}

/** The actions for the chosen profiles, along the bottom of the screen while bulk edit is on. */
export function BulkActionBar({selection, noun, busy, onEnable, onChange, onDelete}: BulkActionBarProps) {
    if (!selection.active) return null
    const none = selection.selected.size === 0
    return (
        <div className="bulk-action-bar" role="toolbar" aria-label="Bulk actions">
            <div className="bulk-action-bar__count" aria-live="polite">
                <strong>{none ? `Choose ${noun[1]} to change` : `${selection.selected.size.toLocaleString()} selected`}</strong>
                {selection.hidden > 0 && (
                    <span className="bulk-action-bar__hidden">{selection.hidden.toLocaleString()} hidden by filters</span>
                )}
                {!none && <button type="button" className="filter-chip-reset" onClick={selection.clear}>Clear</button>}
            </div>
            <div className={`bulk-action-bar__actions${onEnable ? '' : ' is-short'}`}>
                {onEnable && (
                    <>
                        <button type="button" className="btn" disabled={none || busy} onClick={() => onEnable(true)}>
                            <FontAwesomeIcon icon={faIcon('fass', 'play')} aria-hidden="true"/> Enable
                        </button>
                        <button type="button" className="btn" disabled={none || busy} onClick={() => onEnable(false)}>
                            <FontAwesomeIcon icon={faIcon('fass', 'pause')} aria-hidden="true"/> Disable
                        </button>
                    </>
                )}
                <button type="button" className="btn btn-primary" disabled={none || busy} onClick={onChange}>
                    <FontAwesomeIcon icon={faIcon('fass', 'pen-to-square')} aria-hidden="true"/> Change settings
                </button>
                <button type="button" className="btn btn-danger" disabled={none || busy} onClick={onDelete}>
                    <FontAwesomeIcon icon={faIcon('fass', 'trash')} aria-hidden="true"/> Delete
                </button>
            </div>
        </div>
    )
}

/** The profiles a bulk change or delete left as they were, each with why. */
export function SkippedList({result, verb, noun}: {result: BulkResult, verb: string, noun: [string, string]}) {
    return (
        <div className="bulk-result">
            <p>{verb} {countOf(result.done, noun)}.</p>
            {result.skipped.length > 0 && (
                <div className="bulk-skipped">
                    <strong>{countOf(result.skipped.length, noun)} left as {result.skipped.length === 1 ? 'it was' : 'they were'}</strong>
                    <ul>
                        {result.skipped.map((item) => (
                            <li key={item.id}>{item.name} <span>{item.reason}</span></li>
                        ))}
                    </ul>
                </div>
            )}
        </div>
    )
}
