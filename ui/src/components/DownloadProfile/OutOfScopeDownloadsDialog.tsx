import {useEffect, useMemo, useState, type ReactNode} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import toast from 'react-hot-toast'

import ConfirmDialog from '../ConfirmDialog/ConfirmDialog'
import {faIcon} from '../../icons/faIcon'
import {can, getAccess} from '../../lib/access'
import {apiUrl} from '../../lib/api'
import {OperationStartError, useStartOperation} from '../../lib/operations'
import {useDownloadProfileOutOfScope} from '../../lib/queries'
import EpisodeList from '../EpisodeList/EpisodeList'
import type {OutOfScopeDownload, OutOfScopePage} from '../../types/schemas/download_profile'
import type {FilterLike} from './episodeFilters'
import {filterSentence, plainText} from './whichEpisodesText'
import {formatBytes} from '../../utils/formatting'
import './OutOfScopeDownloads.css'

export const KEPT_BY_LABELS: Record<NonNullable<OutOfScopeDownload['keptBy']>, string> = {
    hand: 'Kept by hand',
    keep_filter: 'Kept by a Keep filter',
    keep_question: 'Waiting for your keep answer',
}

/** Whether the signed-in person may delete a profile's downloads and their files. */
export function mayDeleteOutOfScope(): boolean {
    return can('download_profiles', 'manage') && can('managed_downloads', 'manage') && !!getAccess()?.deleteFiles
}

/** "3 downloads (1.2 GiB)" */
export function downloadsSummary(count: number, sizeBytes: number): string {
    const downloads = `${count.toLocaleString()} ${count === 1 ? 'download' : 'downloads'}`
    return sizeBytes ? `${downloads} (${formatBytes(sizeBytes)})` : downloads
}

/**
 * Which out-of-scope downloads to delete: ``notKept`` picks every one that nothing keeps and
 * ``kept`` every kept one, then ``include`` and ``exclude`` add and take away the ones picked by hand.
 */
export type OutOfScopeChoice = {notKept: boolean, kept: boolean, include?: number[], exclude?: number[]}

/** Starts deleting these downloads of the profile in the background; the page shows the progress. */
export function useDeleteOutOfScope(profileId: number, resourceLabel: string) {
    const startOperation = useStartOperation()
    return async (choice: OutOfScopeChoice) => {
        try {
            await startOperation(`${apiUrl()}/download-profiles/${profileId}/out-of-scope-downloads/delete`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(choice),
            })
            toast.success(`Deleting downloads outside the filters of ${resourceLabel}`)
            return true
        } catch (error) {
            const detail = error instanceof OperationStartError ? error.message : undefined
            toast.error(`Could not start deleting downloads${detail ? `: ${detail}` : ''}`)
            return false
        }
    }
}

/** "Left out by: skip if the duration is shorter than 4 minutes" */
export function leftOutByText(
    filter: FilterLike | undefined, typeLabel: (key: string) => string, seasonLabel: (slug: string) => string,
    deleteOlder: boolean,
): string {
    if (!filter) return ''
    const sentence = plainText(filterSentence(filter, typeLabel, seasonLabel, deleteOlder))
    return `Left out by: ${sentence.replace(/^\w/, (c) => c.toLowerCase())}`
}

/**
 * Which listed downloads are picked to delete.
 *
 * Downloads nothing keeps start picked; kept downloads are listed but have their own
 * checkbox, so picking all never deletes one by accident. Each group is kept as whether
 * all of it is picked plus the rows picked or unpicked by hand, so the counts, the size
 * and the delete cover rows that are not loaded yet. Picks start over whenever ``startKey`` changes.
 */
export function useOutOfScopePicks(summary: OutOfScopePage | undefined, startKey: unknown) {
    const [notKept, setNotKept] = useState(true)
    const [kept, setKept] = useState(false)
    /** The rows picked or unpicked by hand, against what their group starts with. */
    const [changed, setChanged] = useState<ReadonlyMap<number, OutOfScopeDownload>>(new Map())

    useEffect(() => {
        setNotKept(true)
        setKept(false)
        setChanged(new Map())
    }, [startKey])

    const startsPicked = (download: OutOfScopeDownload) => download.keptBy === null ? notKept : kept
    const keptTotal = summary?.kept ?? 0
    const notKeptTotal = (summary?.total ?? 0) - keptTotal
    let notKeptCount = notKept ? notKeptTotal : 0
    let keptCount = kept ? keptTotal : 0
    let sizeBytes = (notKept ? (summary?.sizeBytes ?? 0) - (summary?.keptSizeBytes ?? 0) : 0) + (kept ? summary?.keptSizeBytes ?? 0 : 0)
    for (const download of changed.values()) {
        const sign = startsPicked(download) ? -1 : 1
        if (download.keptBy === null) notKeptCount += sign
        else keptCount += sign
        sizeBytes += sign * (download.sizeBytes ?? 0)
    }
    const hand = [...changed.values()]
    const choice: OutOfScopeChoice = {
        notKept,
        kept,
        include: hand.filter((download) => !startsPicked(download)).map((download) => download.id),
        exclude: hand.filter((download) => startsPicked(download)).map((download) => download.id),
    }
    /** Picks or unpicks a whole group, and forgets the hand picks in it. */
    const pickGroup = (isKept: boolean, value: boolean) => {
        if (isKept) setKept(value)
        else setNotKept(value)
        setChanged((current) => new Map([...current].filter(([, download]) => (download.keptBy !== null) !== isKept)))
    }

    return {
        total: summary?.total ?? 0,
        count: notKeptCount + keptCount,
        sizeBytes,
        notKeptTotal,
        notKeptCount,
        keptTotal,
        keptCount,
        choice,
        isPicked: (download: OutOfScopeDownload) => startsPicked(download) !== changed.has(download.id),
        toggle: (download: OutOfScopeDownload) => setChanged((current) => {
            const next = new Map(current)
            if (next.has(download.id)) next.delete(download.id)
            else next.set(download.id, download)
            return next
        }),
        pickNotKept: (value: boolean) => pickGroup(false, value),
        pickKept: (value: boolean) => pickGroup(true, value),
    }
}

export type OutOfScopePicks = ReturnType<typeof useOutOfScopePicks>

/** Picks or unpicks a whole group of downloads: "All 12 downloads picked", "3 of 12 downloads picked". */
function GroupCheckbox({count, total, noun, onChange}: {
    count: number, total: number, noun: (n: number) => string, onChange: (value: boolean) => void,
}) {
    const all = count === total
    return (
        <label className="out-of-scope-all">
            <input
                type="checkbox" checked={all} onChange={() => onChange(!all)}
                ref={(input) => { if (input) input.indeterminate = count > 0 && !all }}
            />
            <span>{all ? 'All' : `${count.toLocaleString()} of`} {total.toLocaleString()} {noun(total)} picked</span>
        </label>
    )
}

/** What a paged list of out-of-scope downloads needs from its infinite query. */
type PagedOutOfScope = {
    data?: {pages: OutOfScopePage[]}
    isPending: boolean
    isError: boolean
    error: Error | null
    refetch: () => unknown
    hasNextPage: boolean
    isFetchingNextPage: boolean
    isFetchNextPageError: boolean
    fetchNextPage: () => unknown
}

type OutOfScopeChecklistProps = {
    query: PagedOutOfScope
    picks: OutOfScopePicks
    /** The sentence of the filter at each position, to say why a download is left out. */
    filterText: (index: number) => string
    typeLabel: (key: string) => string
    /** Said when no download is left out. */
    empty: ReactNode
}

/**
 * The out-of-scope downloads to pick from, loaded a page at a time as the list scrolls.
 * One filter leaving everything out is said once, above the list, instead of on every row.
 */
export function OutOfScopeChecklist({query, picks, filterText, typeLabel, empty}: OutOfScopeChecklistProps) {
    const {data, isPending, isError, error, refetch, hasNextPage, isFetchingNextPage, isFetchNextPageError, fetchNextPage} = query
    const summary = data?.pages[0]
    const listed = useMemo(() => {
        // A download can move to another page while the list loads; show it once.
        const seen = new Set<number>()
        return (data?.pages ?? []).flatMap((page) => page.items).filter((download) => {
            if (seen.has(download.id)) return false
            seen.add(download.id)
            return true
        })
    }, [data])
    const oneFilter = summary?.filterIndexes.length === 1 ? filterText(summary.filterIndexes[0]) : null

    if (isPending) {
        return (
            <p className="modal-text out-of-scope-loading" role="status">
                <FontAwesomeIcon icon={faIcon('fass', 'circle-notch')} spin aria-hidden="true"/>
                <span>Finding the downloads its filters leave out…</span>
            </p>
        )
    }
    if (isError) {
        return (
            <div className="form-error-card" role="alert">
                Could not list these downloads ({error?.message}).{' '}
                <button type="button" className="btn" onClick={() => void refetch()}>Try again</button>
            </div>
        )
    }
    if (!picks.total) return <p className="modal-text">{empty}</p>
    return (
        <>
            {oneFilter && <p className="modal-text out-of-scope-filter">{oneFilter}</p>}
            <div className="out-of-scope-groups">
                {picks.notKeptTotal > 0 && (
                    <GroupCheckbox
                        count={picks.notKeptCount} total={picks.notKeptTotal} onChange={picks.pickNotKept}
                        noun={(n) => n === 1 ? 'download' : 'downloads'}
                    />
                )}
                {picks.keptTotal > 0 && (
                    <GroupCheckbox
                        count={picks.keptCount} total={picks.keptTotal} onChange={picks.pickKept}
                        noun={(n) => n === 1 ? 'download marked to keep' : 'downloads marked to keep'}
                    />
                )}
            </div>
            <EpisodeList
                className="out-of-scope-list"
                typeLabel={typeLabel}
                showSize
                hasMore={hasNextPage}
                loadingMore={isFetchingNextPage}
                moreFailed={isFetchNextPageError}
                loadMore={fetchNextPage}
                rows={listed.map((download) => ({
                    id: download.id,
                    title: download.episodeTitle,
                    note: [
                        !oneFilter && filterText(download.filterIndex),
                        download.keptBy && KEPT_BY_LABELS[download.keptBy],
                        !download.onDisk && 'Not downloaded yet',
                    ].filter(Boolean).join(' • ') || undefined,
                    episodeType: download.episodeType,
                    duration: download.duration,
                    publishedAt: download.publishedAt,
                    sizeBytes: download.sizeBytes,
                    checked: picks.isPicked(download),
                    onToggle: () => picks.toggle(download),
                    toggleLabel: `Delete ${download.episodeTitle}`,
                }))}
            />
        </>
    )
}

type OutOfScopeDownloadsDialogProps = {
    open: boolean
    profileId: number
    resourceLabel: string
    /** The sentence of the filter at each position, to say why a download is left out. */
    filterText: (index: number) => string
    typeLabel: (key: string) => string
    onDismiss: () => void
    onStartingChange?: (starting: boolean) => void
}

/**
 * Lists the profile's downloads that its filters leave out and deletes the ones picked.
 * The dialog closes as soon as the delete starts; it runs in the background.
 */
export default function OutOfScopeDownloadsDialog({
    open, profileId, resourceLabel, filterText, typeLabel, onDismiss, onStartingChange,
}: OutOfScopeDownloadsDialogProps) {
    const remove = useDeleteOutOfScope(profileId, resourceLabel)
    const query = useDownloadProfileOutOfScope(profileId, open)
    const picks = useOutOfScopePicks(query.data?.pages[0], open)

    const start = async () => {
        const choice = picks.choice
        onDismiss()
        onStartingChange?.(true)
        try {
            await remove(choice)
        } finally {
            onStartingChange?.(false)
        }
    }

    return (
        <ConfirmDialog
            open={open}
            title="Delete downloads outside its filters"
            icon={faIcon('fass', 'trash')}
            iconTone="danger"
            className="out-of-scope-dialog"
            onDismiss={onDismiss}
            confirmButton={{
                label: picks.count ? `Delete ${picks.count.toLocaleString()}` : 'Delete',
                className: 'btn btn-danger',
                disabled: !picks.count,
                onClick: () => void start(),
            }}
        >
            <p className="modal-text">
                These downloads were downloaded or adopted by this Download Profile, but its filters leave
                them out now. Downloads you made by hand are not the profile's, so they are never listed or deleted.
                Downloads marked to keep are listed, but picking all leaves them out: they have a checkbox of their own.
            </p>
            <OutOfScopeChecklist
                query={query}
                picks={picks}
                filterText={filterText}
                typeLabel={typeLabel}
                empty="Its filters cover every download it has."
            />
            {picks.total > 0 && (
                <p className="modal-text">
                    {picks.count
                        ? <>Deletes {downloadsSummary(picks.count, picks.sizeBytes)} and their files in the background. This can't be undone.</>
                        : 'Pick the downloads to delete.'}
                </p>
            )}
        </ConfirmDialog>
    )
}
