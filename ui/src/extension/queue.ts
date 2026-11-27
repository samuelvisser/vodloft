/**
 * The extension's own queue of quick downloads. It keeps what the user asked for while VODLoft is down, hands each to
 * VODLoft once it answers, follows it there, and saves the file into the browser's downloads when it is ready. The
 * background script is the only one that changes it; the popup asks it to with a message and shows what it stores.
 */
import type {QuickChoice} from '../types/schemas/quick_download'
import {ext} from './browser'

export type QueuedState =
    /** VODLoft has not taken it yet: it was down, or the user was not signed in. */
    | 'waiting'
    /** VODLoft is fetching the file. */
    | 'working'
    /** The file is ready on VODLoft, to save. */
    | 'ready'
    /** Handed to the browser's downloads. */
    | 'saved'
    | 'failed'

export type QueuedDownload = {
    id: string
    url: string
    sourceKey: string | null
    title: string
    imageUrl: string | null
    choice: QuickChoice
    /** The choice as Quick download names it, such as 1080p MP4. */
    summary: string
    state: QueuedState
    createdAt: number
    /** Why a waiting download waits. */
    waitingFor?: 'vodloft' | 'sign-in'
    quickId?: string
    operationId?: string
    /** VODLoft's operation for it, as its API sent it, for the progress. */
    operation?: Record<string, unknown>
    fileName?: string
    sizeBytes?: number
    format?: string
    /** What went wrong, for a failed download. */
    message?: string
}

/** What the popup asks the background script to do. */
export type QueueMessage =
    | {type: 'queue.add'; download: Omit<QueuedDownload, 'id' | 'state' | 'createdAt'>}
    | {type: 'queue.check'}
    | {type: 'queue.save'; id: string}
    | {type: 'queue.retry'; id: string}
    | {type: 'queue.remove'; id: string}
    | {type: 'queue.clear-finished'}

const QUEUE_KEY = 'quickQueue'
const AUTO_SAVE_KEY = 'autoSave'

export async function loadQueue(): Promise<QueuedDownload[]> {
    const {[QUEUE_KEY]: queue} = await ext.storage.local.get(QUEUE_KEY)
    return Array.isArray(queue) ? queue : []
}

export async function storeQueue(queue: QueuedDownload[]): Promise<void> {
    await ext.storage.local.set({[QUEUE_KEY]: queue})
}

/** Calls ``listener`` with the queue each time the background script changes it. */
export function onQueueChanged(listener: (queue: QueuedDownload[]) => void): () => void {
    const changed = (changes: Record<string, {newValue?: unknown}>, area: string) => {
        if (area === 'local' && QUEUE_KEY in changes) {
            const value = changes[QUEUE_KEY].newValue
            listener(Array.isArray(value) ? value as QueuedDownload[] : [])
        }
    }
    ext.storage.onChanged.addListener(changed)
    return () => ext.storage.onChanged.removeListener(changed)
}

/** Whether files are saved as soon as they are ready, without a click. On unless the user turned it off. */
export async function autoSave(): Promise<boolean> {
    const {[AUTO_SAVE_KEY]: value} = await ext.storage.local.get(AUTO_SAVE_KEY)
    return value !== false
}

export async function setAutoSave(value: boolean): Promise<void> {
    await ext.storage.local.set({[AUTO_SAVE_KEY]: value})
}

export function sendQueueMessage(message: QueueMessage): Promise<void> {
    return ext.runtime.sendMessage(message)
}

export const finished = (download: QueuedDownload) => download.state === 'saved' || download.state === 'failed'
