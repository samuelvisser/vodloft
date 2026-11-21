import type {TaskOperationRead} from '../types/schemas/operation'
import type {ProgressPresentation, ProgressStep} from '../types/progress'
import {PlanSchema, type PlanStage} from '../types/schemas/progress_plan'
import {frontendOperationDefinitions} from './operationDefinitions'
import {ACTIVE_OPERATION_STATUSES, presentDownloadProgress} from './downloadProgress'
import {waitingPresentation, workingPresentation} from './progressPresentation'
import {faIcon} from '../icons/faIcon'
import {planSteps} from './progressPlan'

/** A step in words: what the task says it does, or for a part of a larger action, which action on what. */
function stepLabel(stage: PlanStage): string {
    const definition = (frontendOperationDefinitions as Record<string, {label: string} | undefined>)[stage.code]
    if (definition) return stage.label ? `${definition.label}: ${stage.label}` : definition.label
    return stage.label ?? 'Working'
}

/** The steps of the plan an operation reports, with the one it is on, when it reports one. */
function planOf(operation: TaskOperationRead): {steps: ProgressStep[], main?: ProgressStep} | undefined {
    const parsed = PlanSchema.safeParse(operation.progressMeta?.plan)
    if (!parsed.success || parsed.data.stages.length === 0) return undefined
    const steps = planSteps(parsed.data.stages, stepLabel)
    return {steps, main: steps.find((step) => step.id === parsed.data.main_activity)}
}

export function presentOperationProgress(operation?: TaskOperationRead, starting = false): ProgressPresentation | undefined {
    const presentation = presentWithoutPlan(operation, starting)
    const plan = operation && presentation ? planOf(operation) : undefined
    if (!presentation || !plan) return presentation
    // Its details list the steps; while the step it is on cannot measure itself, it shows that step's name.
    const detail = plan.main ? `${plan.main.label}.` : presentation.detail
    if (presentation.mode === 'indeterminate' && plan.main) {
        return {...presentation, label: `${plan.main.label}...`, compactLabel: `${plan.main.label}...`, detail, steps: plan.steps}
    }
    return {...presentation, detail, steps: plan.steps}
}

function presentWithoutPlan(operation?: TaskOperationRead, starting = false): ProgressPresentation | undefined {
    if (starting && !operation) return workingPresentation('Starting')
    if (!operation || !ACTIVE_OPERATION_STATUSES.has(operation.status)) return undefined
    if (operation.kind === 'media.download' || operation.kind === 'quick.download') return presentDownloadProgress(undefined, operation)
    if (operation.status === 'QUEUED') return waitingPresentation('download_capacity')
    const wait = operation.progressMeta?.wait_state as {reason?: string; message?: string; until?: number | null} | undefined
    if (operation.status === 'WAITING') return waitingPresentation(wait?.reason || 'dependency', wait?.message || operation.message, operation.progress ?? null, wait?.until)
    const batch = operation.progressMeta?.batch as {completed?: number; requested?: number; finishing?: number; failed?: number; canceled?: number} | undefined
    const isBatch = batch != null || operation.kind.includes('bulk_retry') || operation.kind.includes('redownload')
    if (operation.progress == null) return workingPresentation('Working', operation.message || 'Operation in progress.')
    const percent = Math.max(0, Math.min(99, operation.progress))
    const detail = batch
        ? `${batch.completed || 0}/${batch.requested || 0} complete; ${batch.finishing || 0} finishing; ${batch.failed || 0} failed; ${batch.canceled || 0} canceled. Work estimate, not remaining time.`
        : operation.message || 'Operation in progress.'
    return {mode: 'determinate', active: true, percent, label: `${isBatch ? '~' : ''}${percent}%`, detail,
        secondary: batch ? `${batch.completed || 0}/${batch.requested || 0} complete` : undefined,
        estimated: isBatch, icon: faIcon('fass', 'spinner'), canCancel: true, canRetry: false}
}

/** After the new episodes are saved, VODLoft looks at each one's picture; that takes a request per episode. */
function thumbnailCheckLabel(operation: TaskOperationRead): string | null {
    const check = operation.progressMeta?.thumbnails as {checked?: unknown, total?: unknown} | undefined
    if (typeof check?.checked !== 'number' || typeof check.total !== 'number') return null
    return `Checking thumbnails… ${check.checked.toLocaleString()} of ${check.total.toLocaleString()}`
}

/** How far a Collection's indexing is: its percentage when the Source knows the total, otherwise how many episodes it found so far. */
export function presentIndexingStatus(operation: TaskOperationRead): string | null {
    const thumbnails = thumbnailCheckLabel(operation)
    if (thumbnails) return thumbnails
    if (typeof operation.progress === 'number' && operation.progress > 0) return `${operation.progress}%`
    const found = operation.progressMeta?.found
    return typeof found === 'number' ? `${found} episode${found === 1 ? '' : 's'} found` : null
}

export function presentIndexingLabel(operation: TaskOperationRead): string {
    const thumbnails = thumbnailCheckLabel(operation)
    if (thumbnails) return thumbnails
    const status = presentIndexingStatus(operation)
    return status ? `Indexing… ${status}` : 'Indexing…'
}

/** How far a Collection's Sync now scan is: its percentage when the Source knows the total, otherwise the new episodes it found so far. */
export function presentScanningStatus(operation: TaskOperationRead): string | null {
    const thumbnails = thumbnailCheckLabel(operation)
    if (thumbnails) return thumbnails
    if (typeof operation.progress === 'number' && operation.progress > 0) return `${operation.progress}%`
    const found = operation.progressMeta?.found
    return typeof found === 'number' ? `${found} new episode${found === 1 ? '' : 's'} found` : null
}

export function presentScanningLabel(operation: TaskOperationRead): string {
    const thumbnails = thumbnailCheckLabel(operation)
    if (thumbnails) return thumbnails
    const status = presentScanningStatus(operation)
    return status ? `Scanning… ${status}` : 'Scanning…'
}
