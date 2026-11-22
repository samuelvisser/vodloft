import type {ComponentProps} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'

import {faIcon} from '../../icons/faIcon'
import {presentOperationProgress} from '../../lib/operationProgress'
import type {FrontendOperationDefinition} from '../../lib/operationDefinitions'
import type {ProgressPresentation} from '../../types/progress'
import {useActiveOperation} from '../OperationNotifier/OperationNotifier'
import DisabledReason from './DisabledReason'
import ProgressFill from './ProgressFill'
import SimpleSelect from './SimpleSelect'
import './ProgressSelect.css'

function statusText(presentation: ProgressPresentation, activeLabel: string): string {
    if (presentation.mode === 'waiting') return presentation.compactLabel ?? presentation.label
    if (presentation.mode === 'determinate' && presentation.percent != null) {
        return `${activeLabel} · ${Math.round(presentation.percent)}%`
    }
    return activeLabel
}

type Props = Omit<ComponentProps<typeof SimpleSelect>, 'controlAddon' | 'dropdownIndicator'> & {
    'aria-describedby'?: string
    /** The operation that changes this field. While it runs, the field shows its progress and can't be changed. */
    definition: FrontendOperationDefinition
    resourceId?: number | null
    /** Why the field can't be changed while the operation runs, shown on hover and when it is clicked or tapped. */
    busyReason: string
    /** The key in the operation's context that holds the value it changes the field to. While it runs, the field
     *  shows that value instead of its current one. */
    targetValueKey?: string
    /** What the operation is doing, shown with its percentage while it runs, such as "Renumbering episodes". */
    activeLabel: string
    /** Offers a × in place of the chevron that cancels the running operation. Leave it out when the operation
     *  can't be stopped halfway. */
    onCancel?: () => void
    cancelLabel?: string
    /** Shows only an operation this says is about the field, when one operation changes several fields, such as the
     *  feeds and playlists that moved into a collection. */
    appliesTo?: (operation: NonNullable<ReturnType<typeof useActiveOperation>>) => boolean
}

/**
 * A dropdown whose value is changed by an operation. While the operation runs, the field fills from left to right as
 * its progress bar, shows its value as a small title above what the operation is doing, and can't be opened; hovering
 * or clicking it explains why.
 */
export default function ProgressSelect({
    definition, resourceId, busyReason, targetValueKey, activeLabel, onCancel, cancelLabel, isDisabled, className = '',
    value, appliesTo, ...props
}: Props) {
    const active = useActiveOperation(definition.kind, definition.resourceType, resourceId ?? null)
    const operation = active && (!appliesTo || appliesTo(active)) ? active : undefined
    const presentation = presentOperationProgress(operation)
    const running = presentation?.active ? presentation : undefined
    const target = running && targetValueKey ? operation?.context?.[targetValueKey] : undefined
    const cancelText = cancelLabel || `Cancel ${definition.label.toLocaleLowerCase()}`

    return (
        <DisabledReason reason={running ? busyReason : undefined} placement="below-start" as="div">
            {({describedBy, explain}) => (
                <div className={`progress-select-host${running ? ' is-progress' : ''}`} onClick={running ? explain : undefined}>
                    <SimpleSelect
                        {...props}
                        value={typeof target === 'string' ? target : value}
                        className={`${className} progress-select${running ? ` is-progress is-${running.mode}` : ''}${onCancel ? ' has-cancel' : ''}`}
                        isDisabled={isDisabled || !!running}
                        aria-describedby={describedBy ?? props['aria-describedby']}
                        // The whole field is the progress bar: it fills behind the value, the way an Actions menu
                        // item fills while its task runs.
                        controlAddon={running && <ProgressFill presentation={running} className="progress-select-fill"/>}
                        // Stacked like ProgressButton: the value as a small uppercase title, and what is happening in
                        // bold below it.
                        formatOptionLabel={running ? (option) => (
                            <>
                                <span className="progress-select-title">{option.label}</span>
                                <span className="progress-select-status">
                                    {running.mode !== 'determinate' && (
                                        <FontAwesomeIcon className="vl-progress-icon" icon={running.icon}/>
                                    )}
                                    {statusText(running, activeLabel)}
                                </span>
                            </>
                        ) : props.formatOptionLabel}
                        classNames={running ? {...props.classNames, singleValue: () => 'progress-select-value'} : props.classNames}
                        dropdownIndicator={running && onCancel ? (
                            <button
                                type="button"
                                className="progress-select-cancel"
                                title={cancelText}
                                aria-label={cancelText}
                                // The field opens its menu on mouse down; the cancel button must not.
                                onMouseDown={(event) => event.stopPropagation()}
                                onClick={(event) => {
                                    event.stopPropagation()
                                    onCancel()
                                }}
                            >
                                <FontAwesomeIcon icon={faIcon('fass', 'xmark')}/>
                            </button>
                        ) : undefined}
                    />
                </div>
            )}
        </DisabledReason>
    )
}
