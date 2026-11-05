import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'

import {useActiveOperation} from '../OperationNotifier/OperationNotifier'
import ProgressBar from '../common/ProgressBar'
import {presentIndexingLabel, presentScanningLabel} from '../../lib/operationProgress'
import './CollectionIndexingProgress.css'

type Props = {
    collectionId: number
    collectionSlug: string
    className?: string
    pollForStart?: boolean
}

export default function CollectionIndexingProgress({collectionId, className}: Props) {
    const indexingOperation = useActiveOperation('collection.index', 'collection', collectionId)
    // Sync now scans the Collection again; it gets the same banner while it runs.
    const scanningOperation = useActiveOperation('collection.sync', 'collection', collectionId)
    const operation = indexingOperation ?? scanningOperation

    if (!operation) return null

    const progress = typeof operation.progress === 'number' && operation.progress > 0
        ? operation.progress
        : null
    const classes = ['collection-indexing-progress', className].filter(Boolean).join(' ')

    return (
        <div className={classes} aria-live="polite">
            <div className="collection-indexing-label">
                <span>
                    {indexingOperation ? presentIndexingLabel(indexingOperation) : presentScanningLabel(operation)}
                </span>
                {progress == null && <FontAwesomeIcon icon={faIcon('fass', 'spinner')} spin aria-hidden="true"/>}
            </div>
            {progress != null && <ProgressBar value={progress} ariaLabel={indexingOperation ? 'Indexing progress' : 'Scanning progress'}/>}
        </div>
    )
}
