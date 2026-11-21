import {useState} from 'react'
import {useQueryClient} from '@tanstack/react-query'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {toast} from '../../lib/toast'
import {faIcon} from '../../icons/faIcon'
import {removeEpisodePreviewFromStorage, removeSeasonsFromStorage} from '../../lib/cache'
import {episodeQueryKeys} from '../../lib/collectionQueryOptions'
import {BulkCheckFrequencyReg, CheckFrequencyReg, CookiesModeReg, EpisodeOrderReg, SplitChaptersReg} from '../../types/collection'
import BulkChangeDialog, {type BulkFieldSpec} from '../../components/ProfileBulkEdit/BulkChangeDialog'
import BulkDeleteDialog from '../../components/ProfileBulkEdit/BulkDeleteDialog'
import {BulkBar} from '../../components/ProfileBulkEdit/BulkEditControls'
import {bulkAction, countOf} from '../../components/ProfileBulkEdit/bulkApi'
import type {BulkSelection} from '../../components/ProfileBulkEdit/useBulkSelection'

const COLLECTION_FIELDS: BulkFieldSpec[] = [
    {
        key: 'checkFrequency', label: 'How often to check', kind: 'select', defaultValue: 'default', registry: BulkCheckFrequencyReg,
        valueLabel: (value) => CheckFrequencyReg.getLabelLoose(String(value)).toLowerCase(),
        help: 'Give a Collection its own schedule on its Edit page.',
    },
    {
        key: 'episodeOrder', label: 'Order', kind: 'select', defaultValue: 'newest_first', registry: EpisodeOrderReg,
        valueLabel: (value) => EpisodeOrderReg.getLabelLoose(String(value)).toLowerCase(),
        help: 'The order on the Collection page and in podcast apps that follow its RSS feeds.',
    },
    {
        key: 'splitChapters', label: 'Videos with chapters', kind: 'select', defaultValue: 'whole', registry: SplitChaptersReg,
        valueLabel: (value) => (value ? 'split per chapter' : 'kept whole'),
        toApi: (value) => value === 'split',
        help: 'Only changes videos found from now on.',
    },
    {
        key: 'cookiesMode', label: 'Use the cookies file', kind: 'select', defaultValue: 'automatic', registry: CookiesModeReg,
        valueLabel: (value) => CookiesModeReg.getLabelLoose(String(value)).toLowerCase(),
    },
    {
        key: 'genre', label: 'Genre', kind: 'text', defaultValue: '', maxLength: 200, placeholder: 'Documentaries',
        valueLabel: (value) => (value ? String(value) : 'none'),
        help: 'Written into the NFO files for Jellyfin, Emby and Kodi. Leave it empty to remove it.',
    },
    {
        key: 'contentRating', label: 'Content rating', kind: 'text', defaultValue: '', maxLength: 50, placeholder: 'TV-14',
        valueLabel: (value) => (value ? String(value) : 'none'),
        help: 'Leave it empty to remove it.',
    },
]

const NOUNS = {
    collections: ['collection', 'collections'],
    movies: ['movie', 'movies'],
} satisfies Record<string, [string, string]>

const DELETE_NOTES = {
    collections: 'This removes the collections and everything VODLoft indexed of them, with their profiles. Downloaded files already on disk are not removed.',
    movies: 'This removes the movies, their indexed extras and their download history from VODLoft. Downloaded files already on disk are not removed.',
}

type LibraryBulkEditProps = {
    kind: 'collections' | 'movies'
    selection: BulkSelection
    /** The chosen ones' names and slugs, by id. */
    items: ReadonlyMap<number, {title: string, slug: string}>
}

/** The bar of actions for the Library's chosen collections or movies, and the dialogs it opens. */
export default function LibraryBulkEdit({kind, selection, items}: LibraryBulkEditProps) {
    const queryClient = useQueryClient()
    const [dialog, setDialog] = useState<'change' | 'delete' | null>(null)
    const [ids, setIds] = useState<number[]>([])
    const [syncing, setSyncing] = useState(false)
    const noun = NOUNS[kind]
    const endpoint = kind
    const names = ids.flatMap((id) => items.get(id)?.title ?? [])

    const open = (which: 'change' | 'delete') => {
        setIds(selection.ids)
        setDialog(which)
    }

    const refresh = () => Promise.allSettled(kind === 'collections' ? [
        queryClient.invalidateQueries({queryKey: ['collectionsView']}),
        queryClient.invalidateQueries({queryKey: ['collections']}),
        queryClient.invalidateQueries({queryKey: ['collection']}),
        queryClient.invalidateQueries({queryKey: ['creators']}),
        queryClient.invalidateQueries({queryKey: ['libraryCounts']}),
    ] : [
        queryClient.invalidateQueries({queryKey: ['movies']}),
        queryClient.invalidateQueries({queryKey: ['libraryCounts']}),
        queryClient.invalidateQueries({queryKey: ['mediaDownloads']}),
        queryClient.invalidateQueries({queryKey: ['mediaDownloadsView']}),
    ])

    /** What this browser keeps of each collection, which a new order or a delete leaves out of date. */
    const forget = (slugs: string[], everything: boolean) => {
        for (const slug of slugs) {
            removeEpisodePreviewFromStorage(slug)
            queryClient.removeQueries({queryKey: episodeQueryKeys.forCollection(slug)})
            if (everything) {
                removeSeasonsFromStorage(slug)
                queryClient.removeQueries({queryKey: ['collection', slug]})
                queryClient.removeQueries({queryKey: ['seasons', slug]})
            }
        }
    }
    const slugsOf = (chosen: number[]) => chosen.flatMap((id) => items.get(id)?.slug ?? [])

    const sync = async () => {
        setSyncing(true)
        try {
            const result = await bulkAction(endpoint, 'sync', selection.ids)
            if (result.skipped.length) {
                toast(`Started a sync of ${countOf(result.done, noun)}; ${countOf(result.skipped.length, noun)} could not start`)
            } else {
                toast.success(`Started a sync of ${countOf(result.done, noun)}`)
            }
        } catch {
            toast.error(`Could not sync the ${noun[1]}`)
        } finally {
            setSyncing(false)
        }
    }

    if (!selection.active) return null
    const none = selection.selected.size === 0
    return (
        <>
            <BulkBar
                count={selection.selected.size} prompt={`Choose ${noun[1]} to ${kind === 'movies' ? 'delete' : 'change'}`} hidden={selection.hidden}
                onClear={selection.clear} onStop={selection.stop} short={kind === 'movies'}
            >
                {kind === 'collections' && (
                    <>
                        <button type="button" className="btn btn-primary" disabled={none} onClick={() => open('change')}>
                            <FontAwesomeIcon icon={faIcon('fass', 'pen-to-square')} aria-hidden="true"/> Change settings
                        </button>
                        <button type="button" className="btn" disabled={none || syncing} onClick={() => void sync()}>
                            <FontAwesomeIcon icon={faIcon('fass', 'arrows-rotate')} spin={syncing} aria-hidden="true"/> Sync now
                        </button>
                    </>
                )}
                <button type="button" className="btn btn-danger" disabled={none} onClick={() => open('delete')}>
                    <FontAwesomeIcon icon={faIcon('fass', 'trash')} aria-hidden="true"/> Delete
                </button>
            </BulkBar>
            {dialog === 'change' && (
                <BulkChangeDialog
                    endpoint={endpoint}
                    ids={ids}
                    noun={noun}
                    names={names}
                    fields={COLLECTION_FIELDS}
                    onClose={() => setDialog(null)}
                    onChanged={(result) => {
                        // A new order leaves the episodes this browser keeps in the old one.
                        forget(slugsOf(ids), false)
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
                    names={names}
                    note={DELETE_NOTES[kind]}
                    onClose={() => setDialog(null)}
                    onDeleted={() => {
                        if (kind === 'collections') forget(slugsOf(ids), true)
                        selection.clear()
                        void refresh()
                    }}
                />
            )}
        </>
    )
}
