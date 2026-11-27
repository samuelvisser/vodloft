import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import './ProgressVisual.css'
import {faIcon} from '../../icons/faIcon'
import type {ProgressStep} from '../../types/progress'

const STEP_ICONS = {
    pending: faIcon('fass', 'circle'), running: faIcon('fass', 'spinner'), waiting: faIcon('fass', 'clock'),
    completed: faIcon('fass', 'circle-check'), skipped: faIcon('fass', 'ban'), failed: faIcon('fass', 'circle-xmark'),
    canceled: faIcon('fass', 'xmark'),
}
const STEP_STATES = {
    pending: 'To do', running: 'Running', waiting: 'Waiting', completed: 'Done', skipped: 'Skipped', failed: 'Failed',
    canceled: 'Canceled',
}

/** The steps of a plan, each with an icon for where it is, and for the running one how far it is: a task's, a
 * download's, or a save's that the user waits for. */
export default function ProgressSteps({steps, className, label = 'Steps'}: {steps: ProgressStep[], className?: string, label?: string}) {
    return (
        <span className={`vl-progress-steps${className ? ` ${className}` : ''}`} role="list" aria-label={label}>
            {steps.map((step) => (
                <span key={step.id} role="listitem" className={`vl-progress-step is-${step.state}`}>
                    <FontAwesomeIcon icon={STEP_ICONS[step.state]} spin={step.state === 'running'} aria-label={STEP_STATES[step.state]} fixedWidth/>
                    <span className="vl-progress-step-label">
                        {step.label}
                        {step.state === 'running' && step.count && <small className="vl-progress-step-count">{step.count}</small>}
                    </span>
                    {step.state === 'running' && step.percent != null && <span className="vl-progress-step-percent">{step.percent}%</span>}
                </span>
            ))}
        </span>
    )
}
