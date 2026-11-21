import type {ProgressStep} from '../types/progress'
import type {PlanStage} from '../types/schemas/progress_plan'

/** The steps of a task's plan as its details list them, each named by ``label``. Every task that reports a plan,
 * a download or any other, shows its steps through this. */
export function planSteps<S extends PlanStage>(stages: S[], label: (stage: S) => string): ProgressStep[] {
    return stages.map((stage): ProgressStep => ({
        id: stage.id, label: label(stage), state: stage.state,
        percent: stage.fraction == null ? null : Math.max(0, Math.min(100, Math.floor(stage.fraction * 100))),
    }))
}
