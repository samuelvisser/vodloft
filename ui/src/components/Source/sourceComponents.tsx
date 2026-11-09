import type {ComponentType} from 'react'

import DailywireAuthCard from '../DailywireAuth/DailywireAuthCard'
import DailyWireSettingsTab from '../Settings/DailyWireSettingsTab'
import type {SettingsTabProps} from '../Settings/SettingsTabTypes'
import YouTubeApiSettings, {YouTubeApiKey} from './YouTubeApiSettings'

/** The screens a Source brings with it: its own sign-in, its API key and its own settings. The sign-in and
 *  the API key show on the Sites they are for, under Settings › Sources › Authentication. */
type SourceComponents = {
    SignIn?: ComponentType
    ApiKey?: ComponentType
    Settings?: ComponentType<SettingsTabProps>
}

const SOURCE_COMPONENTS: Record<string, SourceComponents> = {
    dailywire: {SignIn: DailywireAuthCard, Settings: DailyWireSettingsTab},
    ytdlp: {ApiKey: YouTubeApiKey, Settings: YouTubeApiSettings},
}

export function sourceComponents(sourceId: string): SourceComponents {
    return SOURCE_COMPONENTS[sourceId] ?? {}
}
