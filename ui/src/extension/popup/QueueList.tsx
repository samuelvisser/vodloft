import {useEffect, useState} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import DownloadProgressStatus from '../../components/DownloadProgress/DownloadProgressStatus'
import {presentDownloadProgress} from '../../lib/downloadProgress'
import {TaskOperationReadSchema} from '../../types/schemas/operation'
import {formatBytes} from '../../utils/formatting'
import {
    autoSave, finished, loadQueue, onQueueChanged, sendQueueMessage, setAutoSave,
    type QueuedDownload,
} from '../queue'

/** How often an open popup asks for news of downloads under way. The background checks on its own every half minute. */
const CHECK_MS = 2000

function Status({download}: {download: QueuedDownload}) {
    if (download.state === 'waiting') {
        return (
            <small className="quick-muted">
                <FontAwesomeIcon icon={faIcon('fass', 'clock')}/>{' '}
                {download.waitingFor === 'sign-in' ? 'Waiting for you to sign in to VODLoft' : download.waitingFor === 'vodloft' ? 'Waiting for VODLoft to be back' : 'Sending to VODLoft'}
            </small>
        )
    }
    if (download.state === 'working') {
        const operation = TaskOperationReadSchema.safeParse(download.operation)
        return <DownloadProgressStatus presentation={presentDownloadProgress(undefined, operation.success ? operation.data : undefined, !operation.success)} details={false}/>
    }
    if (download.state === 'ready') return <small className="quick-ok">Ready to save</small>
    if (download.state === 'saved') return <small className="quick-ok">Saved to your downloads</small>
    return <small className="quick-warn">{download.message ?? 'The download failed.'}</small>
}

/** The extension's quick downloads: waiting for VODLoft, under way there, ready to save, and how the last ones ended. */
export default function QueueList() {
    const [queue, setQueue] = useState<QueuedDownload[]>([])
    const [saveAtOnce, setSaveAtOnce] = useState(true)

    useEffect(() => {
        void loadQueue().then(setQueue)
        void autoSave().then(setSaveAtOnce)
        return onQueueChanged(setQueue)
    }, [])

    const underWay = queue.some((download) => download.state === 'waiting' || download.state === 'working')
    useEffect(() => {
        if (!underWay) return
        void sendQueueMessage({type: 'queue.check'})
        const timer = window.setInterval(() => void sendQueueMessage({type: 'queue.check'}), CHECK_MS)
        return () => window.clearInterval(timer)
    }, [underWay])

    if (!queue.length) return null
    const anyFinished = queue.some(finished)

    const changeAutoSave = async (value: boolean) => {
        setSaveAtOnce(value)
        await setAutoSave(value)
        if (value) await sendQueueMessage({type: 'queue.check'})
    }

    return (
        <section className="quick-list extension-queue" aria-labelledby="extension-queue">
            <div className="quick-list-heading">
                <h2 id="extension-queue">Quick downloads <span className="quick-count">{queue.length}</span></h2>
                {anyFinished && (
                    <button type="button" className="quick-link-button" onClick={() => void sendQueueMessage({type: 'queue.clear-finished'})}>
                        Clear finished
                    </button>
                )}
            </div>
            <label className="quick-check extension-auto-save">
                <input type="checkbox" checked={saveAtOnce} onChange={(event) => void changeAutoSave(event.target.checked)}/>
                <span>Save files to your downloads as soon as they are ready</span>
            </label>
            <ul>
                {queue.map((download) => (
                    <li key={download.id} className="quick-list-row">
                        <span className="quick-list-what">
                            <span className="quick-list-title">{download.title}</span>
                            <small className="quick-muted">
                                {[download.format ?? download.summary, download.sizeBytes ? formatBytes(download.sizeBytes) : null].filter(Boolean).join(' · ')}
                            </small>
                        </span>
                        <span className="quick-list-progress"><Status download={download}/></span>
                        <span className="quick-list-actions">
                            {download.state === 'ready' && (
                                <button type="button" className="btn btn-primary" onClick={() => void sendQueueMessage({type: 'queue.save', id: download.id})}>
                                    <FontAwesomeIcon icon={faIcon('fass', 'download')}/>
                                    Save file
                                </button>
                            )}
                            {download.state === 'failed' && (
                                <button type="button" className="btn" onClick={() => void sendQueueMessage({type: 'queue.retry', id: download.id})}>
                                    Try again
                                </button>
                            )}
                            <button type="button" className="btn" onClick={() => void sendQueueMessage({type: 'queue.remove', id: download.id})}>
                                {finished(download) ? 'Remove' : download.state === 'ready' ? 'Discard' : 'Cancel'}
                            </button>
                        </span>
                    </li>
                ))}
            </ul>
        </section>
    )
}
