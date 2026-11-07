import type {SettingsFieldPath, SettingsRead, SettingsValues} from '../../types/schemas/settings'


export type SettingsErrorPath = SettingsFieldPath | `siteSettings.${string}`

export type UpdateSettingsDraft = (mutator: (next: SettingsValues) => void) => void

export type SettingsTabProps = {
    draft: SettingsValues
    updateDraft: UpdateSettingsDraft
    environmentVariableFor: (path: SettingsFieldPath) => string | undefined
    /** A setting's error, or one Site's under siteSettings, such as siteSettings.youtube.metadataRefresh. */
    errorFor: (path: SettingsErrorPath) => string | undefined
    isFieldExplicit: (path: SettingsFieldPath) => boolean
    isFieldDirty: (path: SettingsFieldPath) => boolean
    downloadStorage?: SettingsRead['downloadStorage']
}
