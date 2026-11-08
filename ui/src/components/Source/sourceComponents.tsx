import type {ComponentType} from 'react'

import DailywireAuthCard from '../DailywireAuth/DailywireAuthCard'
import DailyWireSettingsTab from '../Settings/DailyWireSettingsTab'
import type {SettingsTabProps} from '../Settings/SettingsTabTypes'
import YouTubeApiSettings, {YouTubeApiOnboardingStep} from './YouTubeApiSettings'

/** An extra onboarding step a Source brings, shown after the Sources step under ``label``. */
export type SourceOnboardingStep = {
    label: string
    Step: ComponentType<{onBack: () => void; onContinue: () => void}>
}

/** The screens a Source brings with it: its own sign-in, its own settings and its own onboarding step. */
type SourceComponents = {
    SignIn?: ComponentType
    Settings?: ComponentType<SettingsTabProps>
    /** Only for a Source with ``Feature.API_KEY``: the step that asks for its key. */
    ApiKeyOnboarding?: SourceOnboardingStep
}

const SOURCE_COMPONENTS: Record<string, SourceComponents> = {
    dailywire: {SignIn: DailywireAuthCard, Settings: DailyWireSettingsTab},
    ytdlp: {Settings: YouTubeApiSettings, ApiKeyOnboarding: {label: 'YouTube', Step: YouTubeApiOnboardingStep}},
}

export function sourceComponents(sourceId: string): SourceComponents {
    return SOURCE_COMPONENTS[sourceId] ?? {}
}
