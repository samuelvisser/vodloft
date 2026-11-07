import {z} from 'zod'

import {createSelectRegistry} from '../../utils/selectRegistry'
import {UpgradeImprovementSchema} from './download_profile'

/** What a Site's setting follows: the system default, or a value of its own. */
export const SiteValueModeReg = createSelectRegistry('SiteValueMode', {
    default: {label: 'Default'},
    own: {label: 'Own value'},
}, ['default', 'own'])

/** A switch of a Site: the system default, on or off. */
export const SiteToggleModeReg = createSelectRegistry('SiteToggleMode', {
    default: {label: 'Default'},
    on: {label: 'On'},
    off: {label: 'Off'},
}, ['default', 'on', 'off'])

/** A Site's metadata refresh: the system schedule, one of its own, or none. */
export const SiteRefreshModeReg = createSelectRegistry('SiteRefreshMode', {
    default: {label: 'Default'},
    own: {label: 'Own schedule'},
    off: {label: 'Off'},
}, ['default', 'own', 'off'])

export const SiteSettingGroupSchema = z.enum(['scheduling', 'downloadProfile'])
export type SiteSettingGroup = z.infer<typeof SiteSettingGroupSchema>

/** A setting a Site shows, and what it starts with when the Site has no value of its own. */
const OfferedSettingSchema = z.object({
    key: z.string(),
    /** The Site's preset, or the built-in value of a setting without a system default; null follows the system default. */
    start: z.unknown().nullable(),
    preset: z.boolean(),
})
export type OfferedSetting = z.infer<typeof OfferedSettingSchema>

/** A Site VODLoft knows. Its own values are part of the settings, under siteSettings. */
export const SiteSettingsReadSchema = z.object({
    key: z.string(),
    name: z.string(),
    domains: z.array(z.string()),
    settings: z.array(OfferedSettingSchema),
    upgradeImprovements: z.array(UpgradeImprovementSchema),
})
export type SiteSettingsRead = z.infer<typeof SiteSettingsReadSchema>

export const SitesSettingsReadSchema = z.object({
    specs: z.array(z.object({key: z.string(), group: SiteSettingGroupSchema, hasSystemDefault: z.boolean()})),
    sites: z.array(SiteSettingsReadSchema),
})
export type SitesSettingsRead = z.infer<typeof SitesSettingsReadSchema>

/** How often the upgrade check looks again. */
export const UpgradeRepeatReg = createSelectRegistry('UpgradeRepeat', {
    once: {label: 'Once, then stop'},
    twice: {label: 'Twice, again after 30 days'},
    every: {label: 'Every "check after" days, up to 3 times'},
})

export const UPGRADE_IMPROVEMENT_LABELS: Record<z.infer<typeof UpgradeImprovementSchema>, string> = {
    resolution: 'Resolution',
    sponsorblock: 'SponsorBlock',
    subtitles: 'Subtitles',
    codec: 'Codec',
    length: 'Length',
}
