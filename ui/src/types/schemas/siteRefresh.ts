import {z} from 'zod'

import {createSelectRegistry} from '../../utils/selectRegistry'
import {metadataRefreshIntervals, pendingMinutes} from './settings'

export const SiteRefreshModeReg = createSelectRegistry('SiteRefreshMode', {
    system: {label: 'System setting'},
    own: {label: 'Own schedule'},
    off: {label: 'Off'},
}, ['system', 'own', 'off'])

export const SiteUpcomingReg = createSelectRegistry('SiteUpcoming', {
    system: {label: 'System setting'},
    on: {label: 'On'},
    off: {label: 'Off'},
}, ['system', 'on', 'off'])

export const SiteRhythmReg = createSelectRegistry('SiteRhythm', {
    system: {label: 'System setting'},
    own: {label: 'Own times'},
}, ['system', 'own'])

export const SiteRefreshReadSchema = z.object({
    key: z.string(),
    name: z.string(),
    domains: z.array(z.string()),
    refreshMode: z.enum(['system', 'own', 'off']),
    refreshIntervals: z.string().nullable(),
    // null follows the system setting.
    pendingChecks: z.boolean().nullable(),
    pendingUpcomingMinutes: z.number().nullable(),
    pendingStartingMinutes: z.number().nullable(),
    pendingLiveMinutes: z.number().nullable(),
    refreshes: z.boolean(),
    followsPending: z.boolean(),
})
export type SiteRefreshRead = z.infer<typeof SiteRefreshReadSchema>

export const SiteRefreshFormSchema = z.object({
    refreshMode: z.enum(['system', 'own', 'off']).default('system'),
    refreshIntervals: z.string().default(''),
    pendingChecks: z.enum(['system', 'on', 'off']).default('system'),
    pendingRhythm: z.enum(['system', 'own']).default('system'),
    pendingUpcomingMinutes: pendingMinutes(24 * 60),
    pendingStartingMinutes: pendingMinutes(60),
    pendingLiveMinutes: pendingMinutes(60),
}).superRefine((value, ctx) => {
    if (value.refreshMode !== 'own' && !value.refreshIntervals.trim()) return
    const result = metadataRefreshIntervals.safeParse(value.refreshIntervals)
    if (!result.success) {
        ctx.addIssue({code: 'custom', path: ['refreshIntervals'], message: result.error.issues[0]?.message ?? 'Enter refresh intervals.'})
    }
})
export type SiteRefreshFormIn = z.input<typeof SiteRefreshFormSchema>
export type SiteRefreshFormValues = z.output<typeof SiteRefreshFormSchema>
