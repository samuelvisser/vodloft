import {useCallback, useEffect, useRef, useState} from 'react'

import type {MediaDownloadViewRead} from '../types/schemas/media_download'
import type {DownloadPresentation} from '../types/progress'
import {workingPresentation} from './progressPresentation'

/** How long a row keeps showing its start after the server accepted it, when the live state never catches up. */
const START_HOLD_MS = 20_000

type DownloadStart = {
    /** Tells a start apart from a later one of the same download. */
    token: number
    label: string
    /** The row's operation and status when the start was clicked; a change means the live state caught up. */
    operationId: string | null
    status: string
    sent: boolean
    cancelRequested: boolean
}

function startPresentation(start: DownloadStart): DownloadPresentation {
    if (start.cancelRequested) {
        return {
            status: 'canceling',
            ...workingPresentation('Canceling', 'Stopping the download as soon as the server has started it.'),
            canCancel: false,
            canRetry: false,
        }
    }
    return {
        status: 'preparing',
        ...workingPresentation(start.label, 'Waiting for the server to start the download.'),
        canRetry: false,
    }
}

function caughtUp(start: DownloadStart, download: MediaDownloadViewRead): boolean {
    const operationId = download.operation?.id ?? null
    const changed = operationId !== start.operationId || download.presentation.status !== start.status
    // A cancel waits until the download has stopped, so the row does not flash the queued state in between.
    return changed && !(start.cancelRequested && download.presentation.active)
}

/**
 * Show a retry, re-download or download of an existing download record as started the moment it is clicked.
 *
 * The server answers quickly, but the live progress only arrives with the next pull. Until it does, the row shows
 * an animated "Starting..." state with a cancel button. A cancel clicked before the server answered is sent once
 * the start has been accepted.
 */
export function useDownloadStarts() {
    const starts = useRef(new Map<number, DownloadStart>())
    const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>())
    const nextToken = useRef(0)
    /** The rows `present` turned into starting rows, so a cancel from one of them knows it is still starting. */
    const startingRows = useRef(new WeakSet<MediaDownloadViewRead>())
    const [, setVersion] = useState(0)

    const set = useCallback((id: number, start: DownloadStart | undefined) => {
        if (start) starts.current.set(id, start)
        else starts.current.delete(id)
        setVersion((version) => version + 1)
    }, [])

    useEffect(() => {
        const pending = timers.current
        return () => pending.forEach((timer) => clearTimeout(timer))
    }, [])

    /** Send a start for the download; `send` resolves to whether the server accepted it. */
    const start = useCallback(async (
        download: MediaDownloadViewRead,
        label: string,
        send: () => Promise<boolean>,
        cancel: () => Promise<unknown>,
    ) => {
        clearTimeout(timers.current.get(download.id))
        const token = ++nextToken.current
        const entry: DownloadStart = {
            token,
            label,
            operationId: download.operation?.id ?? null,
            status: download.presentation.status,
            sent: false,
            cancelRequested: false,
        }
        set(download.id, entry)
        const accepted = await send()
        const current = starts.current.get(download.id)
        if (current?.token !== token) return
        if (!accepted) {
            set(download.id, undefined)
            return
        }
        set(download.id, {...current, sent: true})
        timers.current.set(download.id, setTimeout(() => {
            timers.current.delete(download.id)
            if (starts.current.get(download.id)?.token === token) set(download.id, undefined)
        }, START_HOLD_MS))
        if (current.cancelRequested) await cancel()
    }, [set])

    /** Cancel the download, or, while its start is still on its way, cancel it once the server accepted it. */
    const cancel = useCallback(async (download: MediaDownloadViewRead, send: () => Promise<unknown>) => {
        const current = starts.current.get(download.id)
        if (!current || (!startingRows.current.has(download) && caughtUp(current, download))) {
            await send()
            return
        }
        set(download.id, {...current, cancelRequested: true})
        if (current.sent) await send()
    }, [set])

    /** The download as the row shows it: starting, until the live state catches up. */
    const present = useCallback((download: MediaDownloadViewRead): MediaDownloadViewRead => {
        const current = starts.current.get(download.id)
        if (!current || caughtUp(current, download)) return download
        const presentation = startPresentation(current)
        const row = {...download, downloadStatus: presentation.status, presentation}
        startingRows.current.add(row)
        return row
    }, [])

    const isStarting = useCallback((download: MediaDownloadViewRead | undefined) => {
        const current = download && starts.current.get(download.id)
        return Boolean(current && !caughtUp(current, download))
    }, [])

    return {start, cancel, present, isStarting}
}

/** The label a row shows while its start is on its way. */
export function startLabel(download: MediaDownloadViewRead): string {
    if (download.presentation.outcome === 'success') return 'Starting redownload'
    if (download.presentation.status === 'not_downloaded' || download.presentation.active) return 'Starting download'
    return 'Starting retry'
}

export type DownloadStarts = ReturnType<typeof useDownloadStarts>
