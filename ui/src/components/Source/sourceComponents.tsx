import type {ComponentType} from 'react'

import DailywireAuthCard from '../DailywireAuth/DailywireAuthCard'
import DailyWireSettingsTab from '../Settings/DailyWireSettingsTab'
import type {SettingsTabProps} from '../Settings/SettingsTabTypes'
import YouTubeApiSettings from './YouTubeApiSettings'

/** The screens a Source brings with it: its own sign-in and its own settings. */
type SourceComponents = {
    SignIn?: ComponentType
    Settings?: ComponentType<SettingsTabProps>
}

const SOURCE_COMPONENTS: Record<string, SourceComponents> = {
    dailywire: {SignIn: DailywireAuthCard, Settings: DailyWireSettingsTab},
    ytdlp: {Settings: YouTubeApiSettings},
}

export function sourceComponents(sourceId: string): SourceComponents {
    return SOURCE_COMPONENTS[sourceId] ?? {}
}
