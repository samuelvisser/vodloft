import {useRef, useState} from 'react'
import {useQueryClient} from '@tanstack/react-query'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {toast} from '../../lib/toast'
import {faIcon} from '../../icons/faIcon'
import {removeEpisodePreviewFromStorage, removeSeasonsFromStorage} from '../../lib/cache'
import {episodeQueryKeys} from '../../lib/collectionQueryOptions'
import {BulkCheckFrequencyReg, CheckFrequencyReg, CookiesModeReg, EpisodeOrderReg, SplitChaptersReg} from '../../types/collection'
import BulkChangeDialog, {type BulkFieldSpec, type BulkReview} from '../../components/ProfileBulkEdit/BulkChangeDialog'
import BulkSeasonsReview from '../../components/CollectionSeasons/BulkSeasonsReview'
import {capitalized} from '../../types/creator'
import {NamesSchema} from '../../types/schemas/source'
import {BulkFieldSummarySchema, type BulkSummary} from '../../types/schemas/profile_bulk'
import {z} from 'zod'
import BulkDeleteDialog from '../../components/ProfileBulkEdit/BulkDeleteDialog'
import {BulkBar} from '../../components/ProfileBulkEdit/BulkEditControls'
import {bulkAction, bulkDelete, countOf} from '../../components/ProfileBulkEdit/bulkApi'
import {apiUrl} from '../../lib/api'
import DialogSwitch from '../../components/common/DialogSwitch'
import {BulkResultSchema} from '../../types/schemas/profile_bulk'
import type {BulkSelection} from '../../components/ProfileBulkEdit/useBulkSelection'
import type {BulkResult} from '../../types/schemas/profile_bulk'

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

/** What the chosen collections have besides their settings: the feeds of their channels, and their lists. */
const SeasonsSummarySchema = z.object({
    feeds: z.object({key: z.string(), names: NamesSchema, site: z.string(), summary: BulkFieldSummarySchema}).array().default([]),
    listNames: NamesSchema.nullable().default(null),
    looseVideos: BulkFieldSummarySchema.nullable().default(null),
    seasonNames: NamesSchema.nullable().default(null),
})

const ROLE_OPTIONS = [
    {value: 'season', label: 'Own', title: 'A season of its own'},
    {value: 'part', label: 'Part', title: 'Part of the collection'},
    {value: 'off', label: 'Off', title: 'Off'},
]
const ROLE_WORDS: Record<string, string> = {season: 'own season', part: 'part of the collection', off: 'off'}

/** The Seasons dialog's settings the bulk edit changes: the lists switch and each feed of the chosen collections'
 * channels, which only changes the collections whose channel has it. */
function seasonsFields(summary: BulkSummary): BulkFieldSpec[] {
    const {feeds, listNames, looseVideos, seasonNames} = SeasonsSummarySchema.parse(summary)
    const sites = new Set(feeds.map((feed) => feed.site))
    const grouping = seasonNames && {one_season: `One ${seasonNames.singular}`, by_year: `${capitalized(seasonNames.a)} per year`}
    return [
        ...(listNames ? [{
            key: 'linkSeasons', label: `${capitalized(listNames.plural)} and links`, kind: 'switch' as const, defaultValue: true,
            toApi: (value: unknown) => (value ? 'on' : 'off'),
            valueLabel: (value: unknown) => (value === 'off' ? 'off' : 'on'),
            help: `Each ${listNames.singular} keeps what it is in the collection’s Seasons dialog. You see what moves before saving.`,
        }] : []),
        ...feeds.map((feed, index) => ({
            key: `feed${index}`, group: 'feeds', apiKey: feed.key, summary: feed.summary,
            label: sites.size > 1 ? `${capitalized(feed.names.plural)} on ${feed.site}` : capitalized(feed.names.plural),
            kind: 'choice' as const, defaultValue: '', options: ROLE_OPTIONS,
            valueLabel: (value: unknown) => ROLE_WORDS[String(value)] ?? String(value),
            help: 'You see what moves before saving.',
        })),
        ...(looseVideos && grouping ? [{
            key: 'looseVideos', label: 'What is part of the collection goes in', kind: 'choice' as const, defaultValue: '',
            summary: looseVideos,
            options: Object.entries(grouping).map(([value, label]) => ({value, label})),
            valueLabel: (value: unknown) => grouping[String(value) as keyof typeof grouping]?.toLowerCase() ?? String(value),
            help: 'You see what moves before saving.',
        }] : []),
    ]
}

/** Changes to the seasons move downloads, so they are reviewed before they are saved. */
const SEASONS_REVIEW: Omit<BulkReview, 'render'> = {
    wanted: (changes) => 'linkSeasons' in changes || 'feeds' in changes || 'looseVideos' in changes,
    saveLabel: 'Save and move',
}

type Kind = 'creator' | 'collection' | 'movie'
/** What the Library's bulk edit chooses: a creator, a collection or a movie, each by its id. */
export type BulkKey = `${Kind}:${number}`

export function bulkKey(kind: Kind, id: number): BulkKey {
    return `${kind}:${id}`
}

/** The ids of the chosen ones of one kind. */
function idsOf(keys: readonly BulkKey[], kind: Kind): number[] {
    return keys.filter((key) => key.startsWith(`${kind}:`)).map((key) => Number(key.slice(kind.length + 1)))
}

const ENDPOINTS: Record<Kind, string> = {creator: 'creators', collection: 'collections', movie: 'movies'}

type Noun = {singular: string, plural: string}

type LibraryBulkEditProps = {
    kind: 'collections' | 'movies'
    selection: BulkSelection<BulkKey>
    /** The names and slugs of everything the tab can choose, by key. */
    items: ReadonlyMap<BulkKey, {title: string, slug: string, collectionCount?: number}>
    /** What the library's creators are called, such as hosts. */
    creatorNoun: Noun
}

/** The bar of actions for the Library's chosen creators, collections or movies, and the dialogs it opens. */
export default function LibraryBulkEdit({kind, selection, items, creatorNoun}: LibraryBulkEditProps) {
    const queryClient = useQueryClient()
    const [dialog, setDialog] = useState<'change' | 'delete' | null>(null)
    const [keys, setKeys] = useState<BulkKey[]>([])
    const [syncing, setSyncing] = useState(false)
    // Deleting creators keeps their collections, unless this says to delete those too.
    const [withCollections, setWithCollections] = useState(false)
    // Whether the open dialog changed or deleted anything: closing it then ends bulk edit.
    const applied = useRef(false)
    const collectionNoun: [string, string] = ['collection', 'collections']

    const chosen = selection.ids
    const chosenCollections = idsOf(chosen, 'collection')
    const open = (which: 'change' | 'delete') => {
        setKeys(chosen)
        setWithCollections(false)
        applied.current = false
        setDialog(which)
    }
    const close = () => {
        setDialog(null)
        if (applied.current) selection.stop()
    }

    /** What the chosen ones are called together: their own word when they are all one kind, or items. */
    const nounOf = (them: readonly BulkKey[]): [string, string] => {
        const kinds = new Set(them.map((key) => key.split(':')[0] as Kind))
        if (kinds.size > 1) return ['item', 'items']
        if (kinds.has('creator')) return [creatorNoun.singular, creatorNoun.plural]
        if (kinds.has('movie')) return ['movie', 'movies']
        return collectionNoun
    }

    const refresh = () => Promise.allSettled(kind === 'collections' ? [
        queryClient.invalidateQueries({queryKey: ['collectionsView']}),
        queryClient.invalidateQueries({queryKey: ['collections']}),
        queryClient.invalidateQueries({queryKey: ['collection']}),
        queryClient.invalidateQueries({queryKey: ['creators']}),
        queryClient.invalidateQueries({queryKey: ['creator']}),
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
    const collectionSlugs = (ids: number[]) => ids.flatMap((id) => items.get(bulkKey('collection', id))?.slug ?? [])

    const sync = async () => {
        setSyncing(true)
        try {
            const result = await bulkAction('collections', 'sync', chosenCollections)
            selection.stop()
            if (result.skipped.length) {
                toast(`Started a sync of ${countOf(result.done, collectionNoun)}; ${countOf(result.skipped.length, collectionNoun)} could not start`)
            } else {
                toast.success(`Started a sync of ${countOf(result.done, collectionNoun)}`)
            }
        } catch {
            toast.error('Could not sync the collections')
        } finally {
            setSyncing(false)
        }
    }

    const deleteCreators = async (ids: number[]) => {
        const response = await fetch(`${apiUrl()}/creators/bulk/delete`, {
            method: 'POST', headers: {'Content-Type': 'application/json'}, credentials: 'include',
            body: JSON.stringify({ids, deleteCollections: withCollections}),
        })
        if (!response.ok) throw new Error(`The request failed (${response.status})`)
        return BulkResultSchema.parse(await response.json())
    }

    /** Creators first: deleting one keeps its collections, and a chosen collection of it goes after. */
    const removeAll = async (): Promise<BulkResult> => {
        let done = 0
        const skipped: BulkResult['skipped'] = []
        for (const kindOf of ['creator', 'collection', 'movie'] as const) {
            const ids = idsOf(keys, kindOf)
            if (!ids.length) continue
            const result = kindOf === 'creator' ? await deleteCreators(ids) : await bulkDelete(ENDPOINTS[kindOf], ids)
            done += result.done
            skipped.push(...result.skipped)
        }
        return {done, skipped}
    }

    if (!selection.active) return null
    const none = chosen.length === 0
    // The chosen creators' collections, which the switch deletes with them.
    const creatorCollections = idsOf(keys, 'creator').reduce((sum, id) => sum + (items.get(bulkKey('creator', id))?.collectionCount ?? 0), 0)
    const deleteNote = kind === 'movies'
        ? 'This removes the movies, their indexed extras and their download history from VODLoft. Downloaded files already on disk are not removed.'
        : [
            idsOf(keys, 'collection').length > 0 && 'Deleting a collection removes everything VODLoft indexed of it, with its profiles.',
            'Downloaded files already on disk are not removed.',
        ].filter(Boolean).join(' ')
    const partly = (count: number) => !none && count < chosen.length && (
        <span className="bulk-action-count">{count.toLocaleString()}</span>
    )
    return (
        <>
            <BulkBar
                count={chosen.length} prompt={kind === 'movies' ? 'Choose movies to delete' : 'Choose what to change'} hidden={selection.hidden}
                onClear={selection.clear} onStop={selection.stop} short={kind === 'movies'}
            >
                {kind === 'collections' && (
                    <>
                        <button type="button" className="btn btn-primary" disabled={!chosenCollections.length} onClick={() => open('change')}>
                            <FontAwesomeIcon icon={faIcon('fass', 'pen-to-square')} aria-hidden="true"/> Change settings{partly(chosenCollections.length)}
                        </button>
                        <button type="button" className="btn" disabled={!chosenCollections.length || syncing} onClick={() => void sync()}>
                            <FontAwesomeIcon icon={faIcon('fass', 'arrows-rotate')} spin={syncing} aria-hidden="true"/> Sync now{partly(chosenCollections.length)}
                        </button>
                    </>
                )}
                <button type="button" className="btn btn-danger" disabled={none} onClick={() => open('delete')}>
                    <FontAwesomeIcon icon={faIcon('fass', 'trash')} aria-hidden="true"/> Delete
                </button>
            </BulkBar>
            {dialog === 'change' && (
                <BulkChangeDialog
                    endpoint="collections"
                    ids={idsOf(keys, 'collection')}
                    noun={collectionNoun}
                    names={idsOf(keys, 'collection').flatMap((id) => items.get(bulkKey('collection', id))?.title ?? [])}
                    fields={COLLECTION_FIELDS}
                    moreFields={seasonsFields}
                    review={{
                        ...SEASONS_REVIEW,
                        render: ({changes, onReady, onBack, saving}) => (
                            <BulkSeasonsReview ids={idsOf(keys, 'collection')} changes={changes} onReady={onReady} onBack={onBack} saving={saving}/>
                        ),
                    }}
                    onClose={close}
                    onChanged={(result) => {
                        applied.current = true
                        // A new order leaves the episodes this browser keeps in the old one.
                        forget(collectionSlugs(idsOf(keys, 'collection')), false)
                        void refresh()
                        if (result.done) toast.success(`Changed ${countOf(result.done, collectionNoun)}`)
                    }}
                />
            )}
            {dialog === 'delete' && (
                <BulkDeleteDialog
                    endpoint={ENDPOINTS.movie}
                    ids={keys.map((key) => Number(key.split(':')[1]))}
                    noun={nounOf(keys)}
                    names={keys.flatMap((key) => items.get(key)?.title ?? [])}
                    note={deleteNote}
                    remove={removeAll}
                    onClose={close}
                    onDeleted={() => {
                        applied.current = true
                        forget(collectionSlugs(idsOf(keys, 'collection')), true)
                        for (const id of idsOf(keys, 'creator')) {
                            const slug = items.get(bulkKey('creator', id))?.slug
                            if (slug) queryClient.removeQueries({queryKey: ['creator', slug]})
                        }
                        void refresh()
                    }}
                >
                    {creatorCollections > 0 && (
                        <DialogSwitch
                            checked={withCollections} onChange={setWithCollections}
                            label={`Also delete their ${countOf(creatorCollections, collectionNoun)}`}
                            help={withCollections
                                ? 'They are deleted with everything VODLoft indexed of them.'
                                : 'Off, they stay in your library as plain collections.'}
                        />
                    )}
                </BulkDeleteDialog>
            )}
        </>
    )
}
