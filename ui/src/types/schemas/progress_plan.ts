import {z} from 'zod'

/** A time a step waited, and for what. */
export const PlanWaitSchema = z.object({
    reason: z.string(),
    started_at: z.number().optional(),
    finished_at: z.number().nullable().optional(),
    until: z.number().nullable().optional(),
})

/** One step of the plan a task reports its progress by: a download's or any other task's. */
export const PlanStageSchema = z.object({
    id: z.string(), code: z.string(), weight: z.number(), label: z.string().nullable().optional(),
    state: z.enum(['pending', 'running', 'waiting', 'completed', 'skipped', 'failed', 'canceled']),
    started_at: z.number().nullable(), finished_at: z.number().nullable(),
    // How far the running step is, from 0 to 1, or null while it cannot measure itself.
    fraction: z.number().nullable(),
    wait: PlanWaitSchema.nullable(), waits: PlanWaitSchema.array(),
    last_activity_at: z.number().nullable(), deadline_at: z.number().nullable(),
})

export const PlanSchema = z.object({
    main_activity: z.string().nullable(),
    stages: PlanStageSchema.array(),
})
export type PlanStage = z.infer<typeof PlanStageSchema>
export type Plan = z.infer<typeof PlanSchema>
