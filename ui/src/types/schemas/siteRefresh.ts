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
    refreshes: z.boolean(),
})
export type SiteRefreshRead = z.infer<typeof SiteRefreshReadSchema>

export const SiteRefreshFormSchema = z.object({
    refreshMode: z.enum(['system', 'own', 'off']).default('system'),
    refreshIntervals: z.string().default(''),
}).superRefine((value, ctx) => {
    if (value.refreshMode !== 'own' && !value.refreshIntervals.trim()) return
    const result = metadataRefreshIntervals.safeParse(value.refreshIntervals)
    if (!result.success) {
        ctx.addIssue({code: 'custom', path: ['refreshIntervals'], message: result.error.issues[0]?.message ?? 'Enter refresh intervals.'})
    }
})
export type SiteRefreshFormIn = z.input<typeof SiteRefreshFormSchema>
export type SiteRefreshFormValues = z.output<typeof SiteRefreshFormSchema>
