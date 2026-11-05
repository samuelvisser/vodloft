import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'

import {useActiveOperation} from '../OperationNotifier/OperationNotifier'
import ProgressBar from '../common/ProgressBar'
import {presentIndexingLabel} from '../../lib/operationProgress'
import './CollectionIndexingProgress.css'

type Props = {
    collectionId: number
    collectionSlug: string
    className?: string
    pollForStart?: boolean
}

export default function CollectionIndexingProgress({collectionId, className}: Props) {
    const indexingOperation = useActiveOperation('collection.index', 'collection', collectionId)

    if (!indexingOperation) return null

    const progress = typeof indexingOperation.progress === 'number' && indexingOperation.progress > 0
        ? indexingOperation.progress
        : null
    const classes = ['collection-indexing-progress', className].filter(Boolean).join(' ')

    return (
        <div className={classes} aria-live="polite">
            <div className="collection-indexing-label">
                <span>
                    {presentIndexingLabel(indexingOperation)}
                </span>
                {progress == null && <FontAwesomeIcon icon={faIcon('fass', 'spinner')} spin aria-hidden="true"/>}
            </div>
            {progress != null && <ProgressBar value={progress} ariaLabel="Indexing progress"/>}
        </div>
    )
}
