import {useEffect, useMemo, useState} from 'react'
import {Link} from 'react-router-dom'
import toast from 'react-hot-toast'

import ConfirmDialog from '../ConfirmDialog/ConfirmDialog'
import {faIcon} from '../../icons/faIcon'
import {can, getAccess} from '../../lib/access'
import {apiUrl} from '../../lib/api'
import {OperationStartError, useStartOperation} from '../../lib/operations'
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
export function downloadsSummary(downloads: readonly OutOfScopeDownload[]): string {
    const size = downloads.reduce((total, download) => total + (download.sizeBytes ?? 0), 0)
    const count = `${downloads.length.toLocaleString()} ${downloads.length === 1 ? 'download' : 'downloads'}`
    return size ? `${count} (${formatBytes(size)})` : count
}

/** Starts deleting these downloads of the profile in the background; the page shows the progress. */
export function useDeleteOutOfScope(profileId: number, resourceLabel: string) {
    const startOperation = useStartOperation()
    return async (mediaDownloadIds: number[]) => {
        try {
            await startOperation(`${apiUrl()}/download-profiles/${profileId}/out-of-scope-downloads/delete`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({mediaDownloadIds}),
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
    downloads: readonly OutOfScopeDownload[] | undefined
    /** The sentence of the filter at each position, to say why a download is left out. */
    filterText: (index: number) => string
    onDismiss: () => void
    onStartingChange?: (starting: boolean) => void
}

/**
 * Lists the profile's downloads that its filters leave out and deletes the ones picked.
 *
 * Kept downloads are listed but not picked to start with. The dialog closes as soon as
 * the delete starts; it runs in the background.
 */
export default function OutOfScopeDownloadsDialog({
    open, profileId, collectionSlug, resourceLabel, downloads, filterText, onDismiss, onStartingChange,
}: OutOfScopeDownloadsDialogProps) {
    const remove = useDeleteOutOfScope(profileId, resourceLabel)
    const [chosen, setChosen] = useState<ReadonlySet<number>>(new Set())
    const listed = useMemo(() => downloads ?? [], [downloads])

    useEffect(() => {
        if (open) setChosen(new Set(listed.filter((download) => download.keptBy === null).map((download) => download.id)))
    }, [open, listed])

    // One filter leaving everything out is said once, above the list, instead of on every row.
    const filters = new Set(listed.map((download) => download.filterIndex))
    const oneFilter = filters.size === 1 ? filterText(listed[0].filterIndex) : null
    const picked = listed.filter((download) => chosen.has(download.id))
    const allPicked = listed.length > 0 && picked.length === listed.length
    const toggle = (id: number) => setChosen((current) => {
        const next = new Set(current)
        if (next.has(id)) next.delete(id)
        else next.add(id)
        return next
    })

    const start = async () => {
        const ids = picked.map((download) => download.id)
        onDismiss()
        onStartingChange?.(true)
        try {
            await remove(ids)
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
                label: picked.length ? `Delete ${picked.length.toLocaleString()}` : 'Delete',
                className: 'btn btn-danger',
                disabled: !picked.length,
                onClick: () => void start(),
            }}
        >
            <p className="modal-text">
                These downloads were downloaded or adopted by this Download Profile, but its filters leave
                them out now. Downloads you made by hand are not the profile's, so they are never listed or deleted.
            </p>
            {downloads === undefined ? (
                <p className="modal-text">Loading…</p>
            ) : !listed.length ? (
                <p className="modal-text">Its filters cover every download it has.</p>
            ) : (
                <>
                    {oneFilter && <p className="modal-text out-of-scope-filter">{oneFilter}</p>}
                    <label className="out-of-scope-all">
                        <input
                            type="checkbox" checked={allPicked}
                            onChange={() => setChosen(allPicked ? new Set() : new Set(listed.map((download) => download.id)))}
                        />
                        <span>{allPicked ? 'All' : `${picked.length.toLocaleString()} of ${listed.length.toLocaleString()}`} picked</span>
                    </label>
                    <ul className="out-of-scope-list">
                        {listed.map((download) => (
                            <li key={download.id} className={download.keptBy ? 'is-kept' : undefined}>
                                <label>
                                    <input
                                        type="checkbox" checked={chosen.has(download.id)} onChange={() => toggle(download.id)}
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
                    </ul>
                    <p className="modal-text">
                        {picked.length
                            ? <>Deletes {downloadsSummary(picked)} and their files in the background. This can't be undone.</>
                            : 'Pick the downloads to delete.'}
                    </p>
                </>
            )}
        </ConfirmDialog>
    )
}
