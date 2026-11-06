import {z} from 'zod'

import {createSelectRegistry} from '../../utils/selectRegistry'
import {metadataRefreshIntervals} from './settings'

export const SiteRefreshModeReg = createSelectRegistry('SiteRefreshMode', {
    system: {label: 'System schedule'},
    own: {label: 'Own schedule'},
    off: {label: 'Off'},
}, ['system', 'own', 'off'])

export const SiteRefreshReadSchema = z.object({
    key: z.string(),
    name: z.string(),
    domains: z.array(z.string()),
    refreshMode: z.enum(['system', 'own', 'off']),
    refreshIntervals: z.string().nullable(),
    pendingChecks: z.boolean(),
    pendingUpcomingMinutes: z.number(),
    pendingStartingMinutes: z.number(),
    pendingLiveMinutes: z.number(),
    refreshes: z.boolean(),
    checksPending: z.boolean(),
    followsPending: z.boolean(),
})

/** The pending check sweep runs every two minutes, so no interval is shorter; the backend checks the same. */
const pendingMinutes = (max: number) => z.number({error: 'A value is required.'})
    .int('Use whole minutes.')
    .min(2, 'Must be at least 2 minutes.')
    .max(max, `Must be at most ${max} minutes.`)
export type SiteRefreshRead = z.infer<typeof SiteRefreshReadSchema>

export const SiteRefreshFormSchema = z.object({
    refreshMode: z.enum(['system', 'own', 'off']).default('system'),
    refreshIntervals: z.string().default(''),
    pendingChecks: z.boolean().default(true),
    pendingUpcomingMinutes: pendingMinutes(24 * 60).default(60),
    pendingStartingMinutes: pendingMinutes(60).default(2),
    pendingLiveMinutes: pendingMinutes(60).default(5),
}).superRefine((value, ctx) => {
    if (value.refreshMode !== 'own' && !value.refreshIntervals.trim()) return
    const result = metadataRefreshIntervals.safeParse(value.refreshIntervals)
    if (!result.success) {
        ctx.addIssue({code: 'custom', path: ['refreshIntervals'], message: result.error.issues[0]?.message ?? 'Enter refresh intervals.'})
    }
})
export type SiteRefreshFormIn = z.input<typeof SiteRefreshFormSchema>
export type SiteRefreshFormValues = z.output<typeof SiteRefreshFormSchema>
