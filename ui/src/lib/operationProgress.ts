import type {TaskOperationRead} from '../types/schemas/operation'
import type {ProgressPresentation} from '../types/progress'
import {ACTIVE_OPERATION_STATUSES, presentDownloadProgress} from './downloadProgress'
import {waitingPresentation, workingPresentation} from './progressPresentation'
import {faIcon} from '../icons/faIcon'

export function presentOperationProgress(operation?: TaskOperationRead, starting = false): ProgressPresentation | undefined {
    if (starting && !operation) return workingPresentation('Starting')
    if (!operation || !ACTIVE_OPERATION_STATUSES.has(operation.status)) return undefined
    if (operation.kind === 'media.download' || operation.kind === 'quick.download') return presentDownloadProgress(undefined, operation)
    if (operation.status === 'QUEUED') return waitingPresentation('download_capacity')
    const wait = operation.progressMeta?.wait_state as {reason?: string; message?: string; until?: number | null} | undefined
    if (operation.status === 'WAITING') return waitingPresentation(wait?.reason || 'dependency', wait?.message || operation.message, operation.progress ?? null, wait?.until)
    const batch = operation.progressMeta?.batch as {completed?: number; requested?: number; finishing?: number; failed?: number; canceled?: number} | undefined
    const isBatch = batch != null || operation.kind.includes('bulk_retry') || operation.kind.includes('redownload')
    if (operation.progress == null) return workingPresentation('Working', operation.message || 'Operation in progress.')
    const percent = Math.max(0, Math.min(99, operation.progress))
    const detail = batch
        ? `${batch.completed || 0}/${batch.requested || 0} complete; ${batch.finishing || 0} finishing; ${batch.failed || 0} failed; ${batch.canceled || 0} canceled. Work estimate, not remaining time.`
        : operation.message || 'Operation in progress.'
    return {mode: 'determinate', active: true, percent, label: `${isBatch ? '~' : ''}${percent}%`, detail,
        secondary: batch ? `${batch.completed || 0}/${batch.requested || 0} complete` : undefined,
        estimated: isBatch, icon: faIcon('fass', 'spinner'), canCancel: true, canRetry: false}
}

/** A Collection's indexing: its percentage when the Source knows the total, otherwise how many episodes it found so far. */
export function presentIndexingLabel(operation: TaskOperationRead): string {
    if (typeof operation.progress === 'number' && operation.progress > 0) return `Indexing… ${operation.progress}%`
    const found = operation.progressMeta?.found
    return typeof found === 'number' ? `Indexing… ${found} episode${found === 1 ? '' : 's'} found` : 'Indexing…'
}

/** A Collection's Sync now scan: its percentage when the Source knows the total, otherwise the new episodes it found so far. */
export function presentScanningLabel(operation: TaskOperationRead): string {
    if (typeof operation.progress === 'number' && operation.progress > 0) return `Scanning… ${operation.progress}%`
    const found = operation.progressMeta?.found
    return typeof found === 'number' ? `Scanning… ${found} new episode${found === 1 ? '' : 's'} found` : 'Scanning…'
}
