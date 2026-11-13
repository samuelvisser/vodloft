import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {PageHeaderAction} from '../common/PageHeader'
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

/** Bulk edit, which becomes Done while it is on, and Add: the buttons in a profile table's PageHeader. */
export function ProfileTableActions({selection, addTo, addLabel}: ProfileTableActionsProps) {
    return (
        <>
            <PageHeaderAction
                icon={selection.active ? faIcon('fass', 'check') : faIcon('fass', 'list-check')}
                label={selection.active ? 'Done' : 'Bulk edit'}
                variant="secondary"
                keepLabel={selection.active}
                toggled={selection.active}
                onClick={selection.active ? selection.stop : selection.start}
            />
            <PageHeaderAction icon={faIcon('fass', 'plus')} label={addLabel} to={addTo}/>
        </>
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
            <button type="button" className="bulk-action-bar__close" aria-label="Stop bulk edit" title="Stop bulk edit" onClick={selection.stop}>
                <FontAwesomeIcon icon={faIcon('fass', 'xmark')} aria-hidden="true"/>
            </button>
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
