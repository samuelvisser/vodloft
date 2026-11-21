import {z} from 'zod'
import {PlanStageSchema, PlanWaitSchema} from './progress_plan'

export const DownloadWaitSchema = PlanWaitSchema

/** A step of a download attempt: a step of a plan, with its phase, what it works on, and what it transferred. */
export const DownloadStageSchema = PlanStageSchema.extend({
    phase: z.string(), resource: z.string(), asset_id: z.string().nullable().optional(),
    bytes_received: z.number(), total_bytes: z.number().nullable(),
    segments_done: z.number().nullable(), segments_total: z.number().nullable(),
})

export const DownloadExecutionSchema = z.object({
    attempt_id: z.string(), sequence: z.int(),
    phase: z.enum(['preparing', 'transferring', 'finishing', 'complete']),
    main_activity: z.string(), stages: DownloadStageSchema.array(),
    started_at: z.number(), heartbeat_at: z.number(), last_activity_at: z.number(),
    primary_transfer_complete: z.boolean(), canceling: z.boolean(),
    preparation_steps: z.object({code: z.string(), started_at: z.number(), finished_at: z.number()}).array(),
    warnings: z.string().array(),
})
export type DownloadExecution = z.infer<typeof DownloadExecutionSchema>
export type DownloadStage = z.infer<typeof DownloadStageSchema>
