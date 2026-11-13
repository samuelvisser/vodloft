import {forwardRef, useCallback, useImperativeHandle, useState} from 'react'
import {QueryKey, useQueryClient} from '@tanstack/react-query'
import {toast} from 'react-hot-toast'
import {faIcon} from '../../icons/faIcon'

import ConfirmDialog from '../ConfirmDialog/ConfirmDialog'

// Reusable deletion helper built on the generic ConfirmDialog. Use via ref:
// confirmRef.current?.open(item)

export type ConfirmDeleteDialogRef = {
    open: (item: any) => void
    close: () => void
}

type ConfirmDeleteDialogProps = {
    title: string
    // Property name on the item to display as the subject, or a function to compute it
    subjectProp: string | ((item: any) => string)
    // Function that performs the delete request and returns the fetch Promise
    deleteRequest: (item: any) => Promise<Response>
    // Optional list or single React Query keys to invalidate after successful deletion
    invalidateQueries?: QueryKey | QueryKey[]
    // Optional message to show when backend indicates the item is in use and cannot be deleted
    inUseMessage?: string
    // What the toast says once the item is deleted; "Deleted <subject>" when left out
    deletedMessage?: (item: any) => string
    // Runs once the item is deleted, for example to leave the page that showed it
    onDeleted?: (item: any) => void
}

const ConfirmDeleteDialog = forwardRef<ConfirmDeleteDialogRef, ConfirmDeleteDialogProps>(function ConfirmDeleteDialog(props, ref) {
    const {title, subjectProp, deleteRequest, invalidateQueries, inUseMessage, deletedMessage, onDeleted} = props
    const qc = useQueryClient()
    const [item, setItem] = useState<any | null>(null)

    const close = useCallback(() => setItem(null), [])

    useImperativeHandle(ref, () => ({
        open: (i) => setItem(i),
        close,
    }), [close])

    const subjectOf = useCallback((i: any): string => typeof subjectProp === 'function'
        ? subjectProp(i)
        : String(i?.[subjectProp] ?? ''), [subjectProp])

    const onConfirmDelete = useCallback(async () => {
        if (!item) return
        try {
            const r = await deleteRequest(item)
            if (!r || !r.ok) {
                const status = (r as any)?.status ?? 'network'
                let friendly = `Failed to delete item${typeof status === 'number' ? ` (HTTP ${status})` : ''}`
                try {
                    const data = await (r as any)?.json?.().catch(() => null as any)
                    const details: any[] | undefined = (data as any)?.detail
                    if (Array.isArray(details)) {
                        const allErr = details.find((d) => Array.isArray(d?.loc) && d.loc[0] === 'body' && d.loc[1] === '__all__')
                        if (allErr) {
                            if (allErr.type === 'integrity_error') {
                                friendly = inUseMessage || 'This item is in use, it cannot be deleted'
                            } else if (typeof allErr.msg === 'string' && allErr.msg.trim()) {
                                friendly = allErr.msg
                            }
                        }
                    }
                } catch (_) {
                    // ignore parse errors
                }
                console.error(friendly)
                toast.error(friendly)
                close()
                return
            }

            const keysInput = invalidateQueries
            if (keysInput) {
                const isListOfKeys = Array.isArray(keysInput) && (keysInput as any[]).every(Array.isArray)
                const keys = isListOfKeys ? (keysInput as QueryKey[]) : [keysInput as QueryKey]
                await Promise.all(keys.map((key) => qc.invalidateQueries({queryKey: key})))
            }
            toast.success(deletedMessage ? deletedMessage(item) : `Deleted ${subjectOf(item)}`)
            onDeleted?.(item)
        } catch (e) {
            const friendly = 'Failed to delete item (network error)'
            console.error(e)
            toast.error(friendly)
        } finally {
            close()
        }
    }, [item, qc, close, deleteRequest, invalidateQueries, inUseMessage, deletedMessage, onDeleted, subjectOf])

    if (!item) return null

    const subject = subjectOf(item)

    return (
        <ConfirmDialog
            open
            title={title}
            onDismiss={close}
            icon={faIcon('fass', 'trash')}
            iconTone="danger"
            confirmButton={{
                label: 'Delete',
                onClick: onConfirmDelete,
                className: 'btn btn-danger',
            }}
        >
            <p>Are you sure you want to delete "{subject}"? This action cannot be undone.</p>
        </ConfirmDialog>
    )
})

export default ConfirmDeleteDialog
