import type {ProgressStep} from '../types/progress'
import type {Plan, PlanStage} from '../types/schemas/progress_plan'

/** The steps of a task's plan as its details list them, each named by ``label``. Every task that reports a plan,
 * a download or any other, shows its steps through this. */
export function planSteps<S extends PlanStage>(stages: S[], label: (stage: S) => string): ProgressStep[] {
    return stages.map((stage): ProgressStep => ({
        id: stage.id, label: label(stage), state: stage.state,
        percent: stage.fraction == null ? null : Math.max(0, Math.min(100, Math.floor(stage.fraction * 100))),
        ...(stage.total != null && {count: `${stage.done ?? 0}/${stage.total}${stage.unit ? ` ${stage.unit}` : ''}`}),
        // A step that cannot know how many there are counts how many it did so far.
        ...(stage.total == null && stage.done != null && {count: `${stage.done.toLocaleString()}${stage.unit ? ` ${stage.unit}` : ''}`}),
    }))
}

/** The steps of a creator lookup's plan: the Site's own steps of looking the creator up, and those around them. Both
 * the Add creator page and the creator behind a collection's link show a lookup through this. */
export function lookupSteps(plan: Plan): ProgressStep[] {
    return planSteps(plan.stages, (stage) => stage.label ?? 'Working')
}
