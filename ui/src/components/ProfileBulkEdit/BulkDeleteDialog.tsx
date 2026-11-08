import {useState} from 'react'
import ConfirmDialog from '../ConfirmDialog/ConfirmDialog'
import {faIcon} from '../../icons/faIcon'
import type {BulkResult} from '../../types/schemas/profile_bulk'
import {SkippedList} from './BulkEditControls'
import {type BulkEndpoint, bulkDelete, countOf} from './bulkApi'

type BulkDeleteDialogProps = {
    endpoint: BulkEndpoint
    ids: readonly number[]
    noun: [string, string]
    /** Names of the chosen profiles that are on screen. */
    names: string[]
    /** Shown above the warning, such as why a profile in use is skipped. */
    note?: string
    onClose: () => void
    onDeleted: () => void
}

/** Deletes the chosen profiles after asking, and lists any that had to stay. */
export default function BulkDeleteDialog({endpoint, ids, noun, names, note, onClose, onDeleted}: BulkDeleteDialogProps) {
    const [busy, setBusy] = useState(false)
    const [failed, setFailed] = useState(false)
    const [result, setResult] = useState<BulkResult | null>(null)
    const shown = names.slice(0, 5)

    const remove = async () => {
        setBusy(true)
        setFailed(false)
        try {
            const deleted = await bulkDelete(endpoint, ids)
            onDeleted()
            if (deleted.skipped.length) setResult(deleted)
            else onClose()
        } catch {
            setFailed(true)
        } finally {
            setBusy(false)
        }
    }

    if (result) {
        return (
            <ConfirmDialog
                open
                title={`Delete ${countOf(ids.length, noun)}`}
                icon={faIcon('fass', 'trash')}
                iconTone="danger"
                onDismiss={onClose}
                showCancelButton={false}
                confirmButton={{label: 'Close', onClick: onClose, className: 'btn btn-primary'}}
            >
                <SkippedList result={result} verb="Deleted" noun={noun}/>
            </ConfirmDialog>
        )
    }

    return (
        <ConfirmDialog
            open
            title={`Delete ${countOf(ids.length, noun)}?`}
            icon={faIcon('fass', 'trash')}
            iconTone="danger"
            onDismiss={onClose}
            dismissOnOverlayClick={!busy}
            cancelButton={{disabled: busy}}
            confirmButton={{
                label: `Delete ${ids.length.toLocaleString()}`,
                onClick: remove,
                className: 'btn btn-danger',
                disabled: busy,
                icon: busy ? faIcon('fass', 'circle-notch') : undefined,
                iconSpin: busy,
            }}
        >
            {shown.length > 0 && (
                <ul className="bulk-delete-list">
                    {shown.map((name) => <li key={name}>{name}</li>)}
                    {ids.length > shown.length && <li className="is-more">and {(ids.length - shown.length).toLocaleString()} more</li>}
                </ul>
            )}
            {note && <p className="modal-text">{note}</p>}
            <p className="modal-text">This can't be undone.</p>
            {failed && <div className="form-error-card" role="alert">Nothing was deleted. Please try again.</div>}
        </ConfirmDialog>
    )
}
