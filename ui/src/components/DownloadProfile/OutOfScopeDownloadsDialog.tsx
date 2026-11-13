import {useCallback, useEffect, useMemo, useState} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {Link} from 'react-router-dom'
import toast from 'react-hot-toast'

import ConfirmDialog from '../ConfirmDialog/ConfirmDialog'
import {faIcon} from '../../icons/faIcon'
import {can, getAccess} from '../../lib/access'
import {apiUrl} from '../../lib/api'
import {OperationStartError, useStartOperation} from '../../lib/operations'
import {useDownloadProfileOutOfScope} from '../../lib/queries'
import {useLoadMoreOnScroll} from '../../lib/useLoadMoreOnScroll'
import type {OutOfScopeDownload} from '../../types/schemas/download_profile'
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

/** Which of the profile's out-of-scope downloads start picked, before the ones picked or unpicked by hand. */
export type OutOfScopePick = 'none' | 'not_kept' | 'all'

export type OutOfScopeChoice = {pick: OutOfScopePick, include?: number[], exclude?: number[]}

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

type OutOfScopeDownloadsDialogProps = {
    open: boolean
    profileId: number
    collectionSlug: string
    resourceLabel: string
    /** The sentence of the filter at each position, to say why a download is left out. */
    filterText: (index: number) => string
    onDismiss: () => void
    onStartingChange?: (starting: boolean) => void
}

const startsPicked = (pick: OutOfScopePick, download: OutOfScopeDownload) =>
    pick === 'all' || (pick === 'not_kept' && download.keptBy === null)

/**
 * Lists the profile's downloads that its filters leave out and deletes the ones picked.
 *
 * The list loads a page at a time as it scrolls. Kept downloads are listed but not picked
 * to start with. What is picked is kept as where it started (``pick``) and the rows picked
 * or unpicked by hand, so the count, the size and the delete cover rows that are not loaded
 * yet. The dialog closes as soon as the delete starts; it runs in the background.
 */
export default function OutOfScopeDownloadsDialog({
    open, profileId, collectionSlug, resourceLabel, filterText, onDismiss, onStartingChange,
}: OutOfScopeDownloadsDialogProps) {
    const remove = useDeleteOutOfScope(profileId, resourceLabel)
    const {
        data, isPending, isError, error, refetch, hasNextPage, isFetchingNextPage, isFetchNextPageError, fetchNextPage,
    } = useDownloadProfileOutOfScope(profileId, open)
    const [pick, setPick] = useState<OutOfScopePick>('not_kept')
    /** The rows picked or unpicked by hand, against where ``pick`` starts them. */
    const [changed, setChanged] = useState<ReadonlyMap<number, OutOfScopeDownload>>(new Map())

    useEffect(() => {
        if (!open) return
        setPick('not_kept')
        setChanged(new Map())
    }, [open])

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
    const loadMore = useCallback(() => void fetchNextPage(), [fetchNextPage])
    const {rootRef, endRef} = useLoadMoreOnScroll<HTMLUListElement, HTMLLIElement>(
        Boolean(hasNextPage) && !isFetchingNextPage && !isFetchNextPageError, loadMore,
    )

    // One filter leaving everything out is said once, above the list, instead of on every row.
    const oneFilter = summary?.filterIndexes.length === 1 ? filterText(summary.filterIndexes[0]) : null
    const isPicked = (download: OutOfScopeDownload) => startsPicked(pick, download) !== changed.has(download.id)
    const total = summary?.total ?? 0
    let pickedCount = pick === 'all' ? total : pick === 'not_kept' ? total - (summary?.kept ?? 0) : 0
    let pickedSize = !summary ? 0 : pick === 'all' ? summary.sizeBytes : pick === 'not_kept' ? summary.sizeBytes - summary.keptSizeBytes : 0
    for (const download of changed.values()) {
        const sign = startsPicked(pick, download) ? -1 : 1
        pickedCount += sign
        pickedSize += sign * (download.sizeBytes ?? 0)
    }
    const allPicked = total > 0 && pickedCount === total
    const toggle = (download: OutOfScopeDownload) => setChanged((current) => {
        const next = new Map(current)
        if (next.has(download.id)) next.delete(download.id)
        else next.set(download.id, download)
        return next
    })
    const pickAll = (value: OutOfScopePick) => {
        setPick(value)
        setChanged(new Map())
    }

    const start = async () => {
        const hand = [...changed.values()]
        const choice: OutOfScopeChoice = {
            pick,
            include: hand.filter((download) => !startsPicked(pick, download)).map((download) => download.id),
            exclude: hand.filter((download) => startsPicked(pick, download)).map((download) => download.id),
        }
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
                label: pickedCount ? `Delete ${pickedCount.toLocaleString()}` : 'Delete',
                className: 'btn btn-danger',
                disabled: !pickedCount,
                onClick: () => void start(),
            }}
        >
            <p className="modal-text">
                These downloads were downloaded or adopted by this Download Profile, but its filters leave
                them out now. Downloads you made by hand are not the profile's, so they are never listed or deleted.
            </p>
            {isPending ? (
                <p className="modal-text out-of-scope-loading" role="status">
                    <FontAwesomeIcon icon={faIcon('fass', 'circle-notch')} spin aria-hidden="true"/>
                    <span>Finding the downloads its filters leave out…</span>
                </p>
            ) : isError ? (
                <div className="form-error-card" role="alert">
                    Could not list these downloads ({error.message}).{' '}
                    <button type="button" className="btn" onClick={() => void refetch()}>Try again</button>
                </div>
            ) : !total ? (
                <p className="modal-text">Its filters cover every download it has.</p>
            ) : (
                <>
                    {oneFilter && <p className="modal-text out-of-scope-filter">{oneFilter}</p>}
                    <label className="out-of-scope-all">
                        <input type="checkbox" checked={allPicked} onChange={() => pickAll(allPicked ? 'none' : 'all')}/>
                        <span>{allPicked ? 'All' : `${pickedCount.toLocaleString()} of ${total.toLocaleString()}`} picked</span>
                    </label>
                    <ul className="out-of-scope-list" ref={rootRef}>
                        {listed.map((download) => (
                            <li key={download.id} className={download.keptBy ? 'is-kept' : undefined}>
                                <label>
                                    <input
                                        type="checkbox" checked={isPicked(download)} onChange={() => toggle(download)}
                                        aria-label={`Delete ${download.episodeTitle}`}
                                    />
                                    <span className="out-of-scope-copy">
                                        <Link
                                            className="quiet-link"
                                            to={`/collection/${collectionSlug}/episode/${download.episodeSlug}`}
                                            onClick={onDismiss}
                                        >
                                            {download.episodeTitle}
                                        </Link>
                                        <small>
                                            {[
                                                download.publishedAt && new Date(download.publishedAt).toLocaleDateString(undefined, {dateStyle: 'medium'}),
                                                download.onDisk ? formatBytes(download.sizeBytes) : 'Not downloaded yet',
                                                !oneFilter && filterText(download.filterIndex),
                                            ].filter(Boolean).join(' • ')}
                                        </small>
                                        {download.keptBy && (
                                            <span className="out-of-scope-kept">{KEPT_BY_LABELS[download.keptBy]}</span>
                                        )}
                                    </span>
                                </label>
                            </li>
                        ))}
                        {(hasNextPage || isFetchNextPageError) && (
                            <li ref={endRef} className="out-of-scope-more" role="status" aria-busy={isFetchingNextPage}>
                                {isFetchNextPageError ? (
                                    <>Could not load more downloads. <button type="button" className="btn" onClick={loadMore}>Try again</button></>
                                ) : (
                                    <>
                                        <FontAwesomeIcon icon={faIcon('fass', 'circle-notch')} spin aria-hidden="true"/>
                                        <span>Loading more…</span>
                                    </>
                                )}
                            </li>
                        )}
                    </ul>
                    <p className="modal-text">
                        {pickedCount
                            ? <>Deletes {downloadsSummary(pickedCount, pickedSize)} and their files in the background. This can't be undone.</>
                            : 'Pick the downloads to delete.'}
                    </p>
                </>
            )}
        </ConfirmDialog>
    )
}
