import type {ComponentType} from 'react'

import DailywireAuthCard from '../DailywireAuth/DailywireAuthCard'
import DailyWireSettingsTab from '../Settings/DailyWireSettingsTab'
import type {SettingsTabProps} from '../Settings/SettingsTabTypes'
import YouTubeApiSettings, {YouTubeApiKey} from './YouTubeApiSettings'

/** The screens a Source brings with it: its own sign-in, its API key and its own settings. The sign-in and
 *  the API key show on the Sites they are for, under Settings › Sites › Authentication. */
type SourceComponents = {
    SignIn?: ComponentType
    ApiKey?: ComponentType
    Settings?: ComponentType<SettingsTabProps>
    /** What an API key makes better, for the note on Home that asks for one. */
    apiKeyBenefits?: string
}

const SOURCE_COMPONENTS: Record<string, SourceComponents> = {
    dailywire: {SignIn: DailywireAuthCard, Settings: DailyWireSettingsTab},
    ytdlp: {
        ApiKey: YouTubeApiKey, Settings: YouTubeApiSettings,
        apiKeyBenefits: 'With a free YouTube Data API key, a channel of thousands of videos is listed in under a minute '
            + 'instead of hours, new videos are found sooner, searching YouTube is quicker, and the daily check notices '
            + 'removed and private videos.',
    },
}

export function sourceComponents(sourceId: string): SourceComponents {
    return SOURCE_COMPONENTS[sourceId] ?? {}
}
