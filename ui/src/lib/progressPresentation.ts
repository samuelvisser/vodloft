import type {ProgressPresentation} from '../types/progress'
import {faIcon} from '../icons/faIcon'
import {formatDateTimeForDeadline} from '../utils/formatting'

const WAITS: Record<string, [string, string]> = {
    daily_wire_request_cooldown: ['Cooldown', 'Waiting for the source\'s request cooldown. The operation will resume automatically.'],
    daily_wire_request_queue: ['API queue', 'Waiting for a turn to make a request to the source.'],
    request_spacing: ['Waiting', 'Waiting for the next permitted API request.'],
    upstream_retry: ['Retry wait', 'The server requested a delay before retrying.'],
    retry_backoff: ['Retry wait', 'Waiting before retrying the network request.'],
    download_capacity: ['Queued', 'Waiting for an available media download slot.'],
    sidecar_capacity: ['Asset queue', 'Waiting for an auxiliary download slot.'],
    processing_capacity: ['Processing queue', 'Waiting for a local processing slot.'],
    custom_indexes: ['Preparing...', 'Waiting for Custom Index assignments.'],
    previous_attempt: ['Restarting', 'Waiting for the previous download to stop and clean up.'],
    publication_delay: ['Delayed', 'Waiting for the post-publication safety delay before downloading.'],
    downloads_paused: ['Paused', 'Downloads are paused for the night in Settings › Downloads. It starts when the pause ends.'],
    publication_countdown: ['Countdown', 'Waiting for the episode countdown to finish before downloading final media.'],
    site_throttled: ['Throttled', 'The site only offered a low resolution, so its downloads wait a while.'],
}

/** Waits that end at a known time, with how their label and detail say it. */
const DEADLINES: Record<string, {label: string; detail: string}> = {
    publication_delay: {label: 'Delayed until', detail: 'The safety delay ends at'},
    site_throttled: {label: 'Waiting until', detail: 'Trying again at'},
}

function waitDeadline(until?: number | null): string | undefined {
    if (until == null || !Number.isFinite(until)) return undefined

    const deadline = new Date(until * 1000)
    if (Number.isNaN(deadline.getTime())) return undefined
    return formatDateTimeForDeadline(deadline)
}

export function waitingPresentation(
    reason: string,
    backendDetail?: string | null,
    percent: number | null = null,
    until?: number | null,
): ProgressPresentation {
    const value = WAITS[reason]
    const timed = DEADLINES[reason]
    const deadline = timed ? waitDeadline(until) : undefined
    // The backend names the Site that throttled, which the generic text cannot.
    const base = reason === 'site_throttled' ? backendDetail || value?.[1] : value?.[1]
    const frontendDetail = deadline && base ? `${base.replace(/\.$/, '')}. ${timed.detail} ${deadline}.` : base

    return {
        mode: 'waiting',
        active: true,
        percent,
        label: `${deadline ? `${timed.label} ${deadline}` : value?.[0] || 'Waiting'}...`,
        compactLabel: reason === 'publication_delay' ? 'Delayed...' : undefined,
        detail: frontendDetail || backendDetail || 'Waiting for a dependency.',
        icon: faIcon('fass', 'clock'),
        canCancel: true,
        canRetry: true,
    }
}

export function workingPresentation(
    label = 'Preparing',
    detail = label,
    compactLabel = label,
): ProgressPresentation {
    return {
        mode: 'indeterminate',
        active: true,
        percent: null,
        label: `${label}...`,
        compactLabel: `${compactLabel}...`,
        detail,
        icon: faIcon('fass', 'spinner'),
        canCancel: true,
        canRetry: true,
    }
}
