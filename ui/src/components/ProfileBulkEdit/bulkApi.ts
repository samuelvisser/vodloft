import {apiUrl} from '../../lib/api'
import {BulkResultSchema, BulkSummarySchema, type BulkResult, type BulkSummary} from '../../types/schemas/profile_bulk'

/** The API behind one table's bulk edit, such as ``download-profiles``. */
export type BulkEndpoint = string

function post(endpoint: BulkEndpoint, action: string, body: unknown, signal?: AbortSignal) {
    return fetch(`${apiUrl()}/${endpoint}/bulk/${action}`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        credentials: 'include',
        body: JSON.stringify(body),
        signal,
    })
}

async function parsed<T>(response: Response, schema: {parse(value: unknown): T}): Promise<T> {
    if (!response.ok) throw new Error(`The request failed (${response.status})`)
    return schema.parse(await response.json())
}

export async function fetchBulkSummary(endpoint: BulkEndpoint, ids: readonly number[], signal?: AbortSignal): Promise<BulkSummary> {
    return parsed(await post(endpoint, 'summary', {ids}, signal), BulkSummarySchema)
}

/** Sends the changes; the response is left to the caller so form errors can show under the fields. */
export function postBulkChange(endpoint: BulkEndpoint, ids: readonly number[], changes: Record<string, unknown>) {
    return post(endpoint, 'change', {ids, changes})
}

export async function bulkChange(endpoint: BulkEndpoint, ids: readonly number[], changes: Record<string, unknown>): Promise<BulkResult> {
    return parsed(await postBulkChange(endpoint, ids, changes), BulkResultSchema)
}

export async function bulkDelete(endpoint: BulkEndpoint, ids: readonly number[]): Promise<BulkResult> {
    return parsed(await post(endpoint, 'delete', {ids}), BulkResultSchema)
}

/** "3 download profiles", for messages about a bulk change. */
export function countOf(count: number, noun: [string, string]) {
    return `${count.toLocaleString()} ${count === 1 ? noun[0] : noun[1]}`
}
