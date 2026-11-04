import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {Link} from 'react-router-dom'
import {faIcon} from '../../icons/faIcon'
import {can} from '../../lib/access'
import {activeQuickDownloads, useQuickDownloads} from '../../lib/quickDownloads'
import {useOperations} from '../OperationNotifier/OperationNotifier'
import {QuickActiveSummary, quickDownloadOwners} from './QuickDownloadLists'
import './QuickDownload.css'

const SHOWN = 5

/**
 * The quick downloads still running, above the library downloads on Downloads.
 * It only shows them: cancelling and fetching files happen on Quick download.
 */
export default function QuickDownloadsInProgressBox() {
    if (!can('quick_downloads')) return null
    return <InProgressBox/>
}

function InProgressBox() {
    const {operations} = useOperations()
    const {data: quickDownloads} = useQuickDownloads()
    const active = activeQuickDownloads(operations)
    if (!active.length) return null
    const owners = quickDownloadOwners(quickDownloads)
    const hidden = active.length - SHOWN

    return (
        <section className="quick-progress-box" aria-labelledby="quick-progress-box-title">
            <div className="quick-progress-box-head">
                <h2 id="quick-progress-box-title">
                    <FontAwesomeIcon icon={faIcon('fass', 'bolt')} aria-hidden="true"/>
                    Quick downloads in progress <span className="quick-count">{active.length}</span>
                </h2>
                <Link to="/quick-download">Open Quick download</Link>
            </div>
            <ul>
                {active.slice(0, SHOWN).map((operation) => (
                    <li key={operation.id} className="quick-progress-box-row">
                        <QuickActiveSummary operation={operation} ownerName={owners.get(operation.id)}/>
                    </li>
                ))}
            </ul>
            {hidden > 0 && <Link className="quick-progress-box-more" to="/quick-download">and {hidden} more</Link>}
        </section>
    )
}
