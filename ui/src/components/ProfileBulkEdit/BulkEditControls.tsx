import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {Link} from 'react-router-dom'
import {faIcon} from '../../icons/faIcon'
import type {BulkResult} from '../../types/schemas/profile_bulk'
import {countOf} from './bulkApi'
import type {BulkSelection} from './useBulkSelection'
import './ProfileBulkEdit.css'

type ProfileTableActionsProps = {
    selection: BulkSelection
    /** Where Add goes, and what it says, such as "Add media profile". */
    addTo: string
    addLabel: string
}

/**
 * Bulk edit and Add, side by side in a profile table's header. They never stack: when the header is too narrow for
 * their words they become round icon buttons, and the words stay for screen readers and as a tooltip.
 */
export function ProfileTableActions({selection, addTo, addLabel}: ProfileTableActionsProps) {
    return (
        <div className="view-header-actions">
            <BulkEditButton selection={selection}/>
            <Link className="btn btn-primary view-header-action" to={addTo} title={addLabel}>
                <FontAwesomeIcon icon={faIcon('fass', 'plus')} aria-hidden="true"/>
                <span className="view-header-action-label">{addLabel}</span>
            </Link>
        </div>
    )
}

/** Turns bulk edit on beside a table's Add button, and becomes Done while it is on. */
function BulkEditButton({selection}: {selection: BulkSelection}) {
    if (selection.active) {
        return (
            <button type="button" className="btn btn-primary view-header-action" onClick={selection.stop} title="Done">
                <FontAwesomeIcon icon={faIcon('fass', 'check')} aria-hidden="true"/>
                <span className="view-header-action-label">Done</span>
            </button>
        )
    }
    return (
        <button type="button" className="btn btn-secondary view-header-action" onClick={selection.start} title="Bulk edit">
            <FontAwesomeIcon icon={faIcon('fass', 'list-check')} aria-hidden="true"/>
            <span className="view-header-action-label">Bulk edit</span>
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
