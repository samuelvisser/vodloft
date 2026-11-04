import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import type {DownloadPresentation} from '../../types/progress'
import ProgressBar from '../common/ProgressBar'
import ProgressExplanation from '../common/ProgressExplanation'
import './DownloadProgress.css'

/** The status, progress bar and info button of one download, a library download or a quick download. */
export default function DownloadProgressStatus({presentation: state, compact = false, details = true, labelOverride}: {
    presentation: DownloadPresentation; compact?: boolean; details?: boolean; labelOverride?: string
}) {
    const label = labelOverride ?? (compact ? state.compactLabel || state.label : state.label)
    return <span className={`download-progress download-progress-status${compact ? ' is-compact' : ''}`}>
        <span className="download-progress-heading">
            <span className="download-progress-label" role="status" aria-live={state.mode === 'determinate' ? 'off' : 'polite'}><FontAwesomeIcon icon={state.icon} aria-hidden="true"/> {label}</span>
            {details && <ProgressExplanation detail={state.detail + (state.secondary ? ` ${state.secondary}.` : '')}/>}
        </span>
        {state.active && <ProgressBar value={state.percent} mode={state.mode} ariaLabel="Download progress" detail={state.detail}/>}
        {!compact && state.secondary && <small>{state.secondary}</small>}
    </span>
}
