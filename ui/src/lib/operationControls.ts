import type {ActionMenuControl} from '../components/ActionMenu/ActionMenu'
import type {TaskOperationRead} from '../types/schemas/operation'
import type {OperationControlAction} from './operations'
import {faIcon} from '../icons/faIcon'

/** The buttons that restart or cancel a running operation, wherever it shows. Cancel shows only when the operation
 * may be canceled, as the server says of it, so no page offers to stop work that would be left half done. */
export function operationControls(
    operation: TaskOperationRead | undefined,
    label: string,
    {restartable = true, busy, onControl}: {
        restartable?: boolean
        busy: boolean
        onControl: (operationId: string, action: OperationControlAction) => void
    },
): ActionMenuControl[] | undefined {
    if (!operation) return undefined
    const controls: ActionMenuControl[] = []
    if (restartable) controls.push({
        label: `Restart ${label}`, icon: faIcon('fass', 'rotate-right'), disabled: busy,
        onSelect: () => onControl(operation.id, 'restart'),
    })
    if (operation.cancelable) controls.push({
        label: `Cancel ${label}`, icon: faIcon('fass', 'xmark'), tone: 'danger', disabled: busy,
        onSelect: () => onControl(operation.id, 'cancel'),
    })
    return controls.length ? controls : undefined
}
