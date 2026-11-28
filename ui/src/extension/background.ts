/**
 * The extension's background script: it works through the queue of quick downloads while no popup is open. Each
 * download waits until VODLoft answers, is handed to VODLoft's Quick download, followed there, and saved into the
 * browser's downloads once its file is ready. An alarm wakes it while something is under way, also after the browser
 * restarted, so a download sent while VODLoft was down goes out once it is back.
 */
import {apiJson} from '../lib/api'
import {quickDownloadFileUrl, removeQuickDownload, startQuickDownload} from '../lib/quickDownloads'
import {QuickDownloadsSchema} from '../types/schemas/quick_download'
import {TaskOperationReadSchema} from '../types/schemas/operation'
import {apiVersionProblem, ext, messageOf, signedOut, storedAddress, unreachable, connectTo} from './browser'
import {
    autoSave, finished, loadQueue, storeQueue,
    type QueueMessage, type QueuedDownload,
} from './queue'

const ALARM = 'vodloft-queue'
const FAILED_STATUSES = new Set(['FAILED', 'PARTIAL', 'CANCELED'])
/** Saved and failed downloads stay in the list this long, so the user sees how they ended. */
const KEEP_FINISHED_MS = 24 * 60 * 60 * 1000

type Patch = Partial<QueuedDownload>

/** Changes to the queue, one at a time: the popup's messages and the alarm may come in together. */
let changing: Promise<unknown> = Promise.resolve()
function change<T>(work: (queue: QueuedDownload[]) => Promise<T> | T): Promise<T> {
    const next = changing.then(async () => {
        const queue = await loadQueue()
        const result = await work(queue)
        await storeQueue(queue)
        await showCount(queue)
        return result
    })
    changing = next.catch(() => undefined)
    return next
}

function patch(queue: QueuedDownload[], id: string, values: Patch): void {
    const index = queue.findIndex((download) => download.id === id)
    if (index >= 0) queue[index] = {...queue[index], ...values}
}

/** The number on the toolbar icon: files ready to save, or else the downloads still under way. */
async function showCount(queue: QueuedDownload[]): Promise<void> {
    const ready = queue.filter((download) => download.state === 'ready').length
    const busy = queue.filter((download) => download.state === 'waiting' || download.state === 'working').length
    await ext.action.setBadgeText({text: ready ? String(ready) : busy ? String(busy) : ''})
    await ext.action.setBadgeBackgroundColor({color: ready ? '#16a34a' : '#3b82f6'})
}

async function wakeWhileBusy(queue: QueuedDownload[]): Promise<void> {
    const busy = queue.some((download) => download.state === 'waiting' || download.state === 'working'
        || (download.state === 'ready' && !download.fileName))
    if (busy) await ext.alarms.create(ALARM, {periodInMinutes: 0.5})
    else await ext.alarms.clear(ALARM)
}

/** Hand every waiting download to VODLoft. Stops at the first one VODLoft does not answer for. */
async function send(queue: QueuedDownload[]): Promise<void> {
    for (const download of queue.filter((item) => item.state === 'waiting')) {
        try {
            const accepted = await startQuickDownload(download.url, download.sourceKey ?? undefined, download.choice)
            patch(queue, download.id, {
                state: 'working', quickId: accepted.quickDownloadId, operationId: accepted.operationId, waitingFor: undefined,
            })
        } catch (exc) {
            if (unreachable(exc)) {
                patch(queue, download.id, {waitingFor: 'vodloft'})
                return
            }
            if (signedOut(exc)) {
                patch(queue, download.id, {waitingFor: 'sign-in'})
                return
            }
            patch(queue, download.id, {state: 'failed', message: messageOf(exc)})
        }
    }
}

/** Follow the downloads VODLoft is working on, and notice the files it has ready. */
async function follow(queue: QueuedDownload[]): Promise<void> {
    const followed = queue.filter((download) => download.state === 'working' || download.state === 'ready')
    if (!followed.length) return
    const quick = await apiJson('/quick-downloads', QuickDownloadsSchema.parse)
    const ready = new Map(quick.ready.map((file) => [file.id, file]))
    const active = new Map(quick.active.map((entry) => [entry.operation.id, entry.operation]))
    for (const download of followed) {
        const file = download.quickId ? ready.get(download.quickId) : undefined
        if (file) {
            patch(queue, download.id, {
                state: download.state === 'working' ? 'ready' : download.state,
                fileName: file.fileName, sizeBytes: file.sizeBytes, format: file.format,
            })
            continue
        }
        if (download.state === 'ready') {
            patch(queue, download.id, {state: 'failed', message: 'VODLoft deleted the file before it was saved.'})
            continue
        }
        const operation = download.operationId ? active.get(download.operationId) : undefined
        if (operation) {
            patch(queue, download.id, {operation: {...operation}})
            continue
        }
        // Neither working nor ready: it ended, or has only just been queued.
        if (!download.operationId) continue
        try {
            const ended = await apiJson(`/operations/${encodeURIComponent(download.operationId)}`, TaskOperationReadSchema.parse)
            if (FAILED_STATUSES.has(ended.status)) {
                patch(queue, download.id, {
                    state: 'failed', operation: {...ended},
                    message: ended.status === 'CANCELED' ? 'Canceled in VODLoft.' : ended.error || ended.message || 'The download failed.',
                })
            } else {
                patch(queue, download.id, {operation: {...ended}})
            }
        } catch (exc) {
            if (!unreachable(exc)) patch(queue, download.id, {state: 'failed', message: messageOf(exc)})
            else throw exc
        }
    }
}

/** Into the browser's downloads, as the file VODLoft named it. The browser sends the VODLoft session along. */
async function save(queue: QueuedDownload[], download: QueuedDownload): Promise<void> {
    if (!download.quickId) return
    try {
        await ext.downloads.download({url: quickDownloadFileUrl(download.quickId), filename: download.fileName, conflictAction: 'uniquify'})
        patch(queue, download.id, {state: 'saved'})
    } catch (exc) {
        patch(queue, download.id, {state: 'failed', message: `The browser could not save the file: ${messageOf(exc)}`})
    }
}

async function check(queue: QueuedDownload[]): Promise<void> {
    const now = Date.now()
    queue.splice(0, queue.length, ...queue.filter((download) => !finished(download) || now - download.createdAt < KEEP_FINISHED_MS))
    const address = await storedAddress()
    if (address) {
        connectTo(address)
        try {
            const problem = await apiVersionProblem(address)
            // A download VODLoft cannot take fails with the reason, rather than wait for an update that may not come.
            if (problem) {
                for (const download of queue.filter((item) => item.state === 'waiting')) {
                    patch(queue, download.id, {state: 'failed', message: problem, waitingFor: undefined})
                }
            }
            await send(queue)
            await follow(queue)
        } catch (exc) {
            // VODLoft went away while it was followed: the alarm tries again.
            if (!unreachable(exc) && !signedOut(exc)) console.warn('VODLoft queue', exc)
        }
        if (await autoSave()) {
            for (const download of queue.filter((item) => item.state === 'ready' && item.fileName)) await save(queue, download)
        }
    }
    await wakeWhileBusy(queue)
}

async function handle(message: QueueMessage): Promise<void> {
    switch (message.type) {
        case 'queue.add':
            await change((queue) => {
                queue.unshift({...message.download, id: crypto.randomUUID(), state: 'waiting', createdAt: Date.now()})
            })
            break
        case 'queue.save':
            await change(async (queue) => {
                const download = queue.find((item) => item.id === message.id)
                const address = await storedAddress()
                if (download?.state === 'ready' && address) {
                    connectTo(address)
                    await save(queue, download)
                }
            })
            return
        case 'queue.retry':
            await change((queue) => patch(queue, message.id, {
                state: 'waiting', quickId: undefined, operationId: undefined, operation: undefined, message: undefined,
            }))
            break
        case 'queue.remove':
            await change(async (queue) => {
                const download = queue.find((item) => item.id === message.id)
                const address = await storedAddress()
                // Stop VODLoft's work on it, or delete its file there, too.
                if (download?.quickId && address && (download.state === 'working' || download.state === 'ready')) {
                    connectTo(address)
                    await removeQuickDownload(download.quickId).catch(() => undefined)
                }
                queue.splice(0, queue.length, ...queue.filter((item) => item.id !== message.id))
            })
            return
        case 'queue.clear-finished':
            await change((queue) => { queue.splice(0, queue.length, ...queue.filter((item) => !finished(item))) })
            return
        case 'queue.check':
            break
    }
    await change(check)
}

ext.runtime.onMessage.addListener((message: QueueMessage, _sender: unknown, respond: (value?: unknown) => void) => {
    if (typeof message?.type !== 'string' || !message.type.startsWith('queue.')) return false
    handle(message).then(() => respond(), (exc) => respond({error: messageOf(exc)}))
    // The answer comes later.
    return true
})

ext.alarms.onAlarm.addListener((alarm: {name: string}) => {
    if (alarm.name === ALARM) void change(check)
})

ext.runtime.onStartup?.addListener(() => void change(check))
ext.runtime.onInstalled?.addListener(() => void change(check))
