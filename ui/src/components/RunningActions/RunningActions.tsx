import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import type {ActionMenuItem} from '../ActionMenu/ActionMenu'
import ProgressExplanation from '../common/ProgressExplanation'
import ProgressFill from '../common/ProgressFill'
import {presentOperationProgress} from '../../lib/operationProgress'
import './RunningActions.css'

export type RunningAction = Pick<ActionMenuItem, 'label' | 'icon' | 'operation' | 'starting' | 'presentation' | 'controls'> & {
    /** Says how far the action is in place of its percentage, such as how many episodes indexing found. */
    status?: string
}

type Props = {
    /** A page's actions; only those that are starting or running show. */
    actions: RunningAction[]
    className?: string
}

/** The actions running for the item a page shows, one compact row each, so they show without opening the Actions menu. */
export default function RunningActions({actions, className}: Props) {
    const running = actions.flatMap((action) => {
        const presentation = action.presentation ?? presentOperationProgress(action.operation, action.starting)
        return presentation ? [{action, presentation}] : []
    })
    if (running.length === 0) return null

    return (
        <ul className={['running-actions', className].filter(Boolean).join(' ')} aria-label="Running actions" aria-live="polite">
            {running.map(({action, presentation}) => (
                <li key={action.operation?.id ?? action.label} className="running-action">
                    <ProgressFill presentation={presentation} className="running-action-progress"/>
                    {action.icon && <FontAwesomeIcon className="running-action-icon" icon={action.icon} aria-hidden="true"/>}
                    <span className="running-action-text">
                        <span className="running-action-label">{action.label}</span>
                        <span className="running-action-status">
                            {action.status ?? presentation.compactLabel ?? presentation.label}
                        </span>
                    </span>
                    <ProgressExplanation detail={presentation.detail} buttonClassName="running-action-control"/>
                    {action.controls?.map((control) => (
                        <button
                            key={control.label}
                            type="button"
                            className={`running-action-control${control.tone === 'danger' ? ' is-danger' : ''}`}
                            aria-label={control.label}
                            title={control.label}
                            disabled={control.disabled}
                            onClick={control.onSelect}
                        >
                            <FontAwesomeIcon icon={control.icon} aria-hidden="true"/>
                        </button>
                    ))}
                </li>
            ))}
        </ul>
    )
}
