import {useEffect, useState} from 'react'
import {useQuery, useQueryClient} from '@tanstack/react-query'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import toast from '../../lib/toast'

import ConfirmDialog from '../ConfirmDialog/ConfirmDialog'
import '../ChangeIdentificationDialog/ChangeIdentificationDialog.css'
import {faIcon} from '../../icons/faIcon'
import {previewReconcile, reconcile} from '../../lib/queries'
import {CollectionMoves} from '../../pages/creator/MoveSectionsDialog'
import type {ReconcileResult} from '../../types/schemas/creator'

type Props = {
    open: boolean
    /** The API path of what moves: `/creators/<slug>`, `/collections/<slug>` or `/episodes/<slug>`. */
    path: string
    /** What moves, such as "the episodes of Northwind Workshop". */
    what: string
    onDismiss: () => void
    onDone?: (result: ReconcileResult) => void | Promise<void>
}

/** Asks before the Move action of a creator, a collection or one episode puts its Reassigned and Moved episodes
 *  where they belong now, saying for each collection what leaves and joins it and what is numbered, renamed and
 *  rewritten again: the same dialog as moving feeds and lists on a creator's Edit page. */
export default function ReconcileDialog({open, path, what, onDismiss, onDone}: Props) {
    const queryClient = useQueryClient()
    const [renumber, setRenumber] = useState<Record<string, boolean>>({})
    const [error, setError] = useState<string | null>(null)
    useEffect(() => {
        if (open) {
            setRenumber({})
            setError(null)
        }
    }, [open])

    const {data: preview, isLoading, isError, error: previewError} = useQuery({
        queryKey: ['reconcilePreview', path],
        enabled: open,
        gcTime: 0,
        queryFn: ({signal}) => previewReconcile(path, signal),
    })

    const confirm = async () => {
        setError(null)
        try {
            const result = await reconcile(path, renumber)
            toast.success(`Moving ${what}`)
            await Promise.all([
                queryClient.invalidateQueries({queryKey: ['collection']}),
                queryClient.invalidateQueries({queryKey: ['creator']}),
                queryClient.invalidateQueries({queryKey: ['episode']}),
                queryClient.invalidateQueries({queryKey: ['movesWaiting']}),
            ])
            await onDone?.(result)
            onDismiss()
        } catch (exc) {
            setError(exc instanceof Error ? exc.message : 'VODLoft could not move them.')
        }
    }

    return (
        <ConfirmDialog
            open={open}
            title={`Move ${what}?`}
            onDismiss={onDismiss}
            icon={faIcon('fass', 'arrow-right-arrow-left')}
            className="change-identification-dialog move-sections-dialog"
            confirmButton={{label: 'Move', onClick: confirm, className: 'btn btn-primary', disabled: !preview}}
        >
            <p className="help">
                What is downloaded waits where it is until you move it: moving renames its files into their new place, or
                downloads it again there when that place downloads it with another Local Media Profile.
            </p>
            {isLoading && (
                <p className="change-identification-loading" role="status">
                    <FontAwesomeIcon icon={faIcon('fass', 'spinner')} spin aria-hidden="true"/>
                    Looking at what changes…
                </p>
            )}
            {isError && (
                <p className="error" role="alert">
                    {previewError instanceof Error && !(previewError instanceof TypeError) && previewError.message
                        ? previewError.message : 'VODLoft could not look up what the move does.'}
                </p>
            )}
            {preview?.collections.map((collection) => (
                <CollectionMoves
                    key={collection.slug}
                    collection={collection}
                    renumber={renumber[collection.slug] ?? true}
                    onRenumber={(again) => setRenumber((current) => ({...current, [collection.slug]: again}))}
                />
            ))}
            {error && <p className="error" role="alert">{error}</p>}
        </ConfirmDialog>
    )
}
