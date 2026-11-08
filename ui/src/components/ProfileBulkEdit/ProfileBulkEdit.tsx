import {useState} from 'react'
import {useQueryClient} from '@tanstack/react-query'
import {toast} from 'react-hot-toast'
import type {DataTableSelection} from '../DataTable/DataTable'
import BulkChangeDialog, {type BulkFieldSpec} from './BulkChangeDialog'
import BulkDeleteDialog from './BulkDeleteDialog'
import {BulkActionBar} from './BulkEditControls'
import {type BulkEndpoint, bulkChange, countOf} from './bulkApi'
import type {BulkSelection} from './useBulkSelection'

/** The DataTable side of a bulk selection, for rows keyed by their profile's id. */
export function tableSelection(selection: BulkSelection): DataTableSelection | undefined {
    if (!selection.active) return undefined
    return {
        isSelected: (key) => selection.selected.has(Number(key)),
        onToggle: (key) => selection.toggle(Number(key)),
        allState: selection.allState,
        onToggleAll: selection.toggleAll,
    }
}

type ProfileBulkEditProps = {
    selection: BulkSelection
    endpoint: BulkEndpoint
    noun: [string, string]
    /** The names of the profiles on screen, by id. */
    names: ReadonlyMap<number, string>
    fields: BulkFieldSpec[]
    /** Shows Enable and Disable, for profiles that can be switched off. */
    canEnable?: boolean
    deleteNote?: string
    /** The queries to load again after a change, such as the table's. */
    invalidate: readonly (readonly unknown[])[]
}

/** The bar of actions for the chosen profiles, and the dialogs it opens. */
export default function ProfileBulkEdit({selection, endpoint, noun, names, fields, canEnable, deleteNote, invalidate}: ProfileBulkEditProps) {
    const queryClient = useQueryClient()
    const [dialog, setDialog] = useState<'change' | 'delete' | null>(null)
    const [busy, setBusy] = useState(false)
    const [ids, setIds] = useState<number[]>([])

    const refresh = () => Promise.allSettled([
        ...invalidate.map((queryKey) => queryClient.invalidateQueries({queryKey})),
        queryClient.invalidateQueries({queryKey: ['profileTableIds']}),
    ])
    const shownNames = ids.flatMap((id) => names.get(id) ?? [])

    const open = (kind: 'change' | 'delete') => {
        setIds(selection.ids)
        setDialog(kind)
    }

    const setEnabled = async (enableProfile: boolean) => {
        setBusy(true)
        try {
            const result = await bulkChange(endpoint, selection.ids, {enableProfile})
            await refresh()
            const verb = enableProfile ? 'Enabled' : 'Disabled'
            if (result.skipped.length) {
                toast(`${verb} ${countOf(result.done, noun)}; ${countOf(result.skipped.length, noun)} left as they were`)
            } else {
                toast.success(`${verb} ${countOf(result.done, noun)}`)
            }
        } catch {
            toast.error(`Could not ${enableProfile ? 'enable' : 'disable'} the ${noun[1]}`)
        } finally {
            setBusy(false)
        }
    }

    return (
        <>
            <BulkActionBar
                selection={selection}
                noun={noun}
                busy={busy}
                onEnable={canEnable ? setEnabled : undefined}
                onChange={() => open('change')}
                onDelete={() => open('delete')}
            />
            {dialog === 'change' && (
                <BulkChangeDialog
                    endpoint={endpoint}
                    ids={ids}
                    noun={noun}
                    names={shownNames}
                    fields={fields}
                    onClose={() => setDialog(null)}
                    onChanged={(result) => {
                        void refresh()
                        if (result.done) toast.success(`Changed ${countOf(result.done, noun)}`)
                    }}
                />
            )}
            {dialog === 'delete' && (
                <BulkDeleteDialog
                    endpoint={endpoint}
                    ids={ids}
                    noun={noun}
                    names={shownNames}
                    note={deleteNote}
                    onClose={() => setDialog(null)}
                    onDeleted={() => {
                        selection.clear()
                        void refresh()
                    }}
                />
            )}
        </>
    )
}
