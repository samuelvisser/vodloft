import {z} from 'zod'

import {createSelectRegistry} from '../../utils/selectRegistry'

export const SiteRefreshModeReg = createSelectRegistry('SiteRefreshMode', {
    default: {label: 'Default'},
    own: {label: 'Own schedule'},
    off: {label: 'Off'},
}, ['default', 'own', 'off'])

export const SiteUpcomingReg = createSelectRegistry('SiteUpcoming', {
    default: {label: 'Default'},
    on: {label: 'On'},
    off: {label: 'Off'},
}, ['default', 'on', 'off'])

export const SiteRhythmReg = createSelectRegistry('SiteRhythm', {
    default: {label: 'Default'},
    own: {label: 'Own times'},
}, ['default', 'own'])

/** A Site VODLoft knows. Its own scheduling is part of the settings, under siteSchedules. */
export const SiteRefreshReadSchema = z.object({
    key: z.string(),
    name: z.string(),
    domains: z.array(z.string()),
    refreshes: z.boolean(),
    followsPending: z.boolean(),
    // The schedule the Site follows unless it has its own; null follows the system schedule.
    defaultRefreshIntervals: z.string().nullable(),
})
export type SiteRefreshRead = z.infer<typeof SiteRefreshReadSchema>
