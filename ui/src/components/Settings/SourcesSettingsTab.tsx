import {useSources} from '../../lib/queries'
import {SourceFeature, SourceRead, sourceHas} from '../../types/schemas/source'
import SourceCookiesCard from '../Source/SourceCookiesCard'
import SourceDomainsCard from '../Source/SourceDomainsCard'
import SourceProgramCard from '../Source/SourceProgramCard'
import SourceSection from '../Source/SourceSection'
import {sourceComponents} from '../Source/sourceComponents'
import type {SettingsTabProps} from './SettingsTabTypes'

const FEATURE_LABELS: Record<string, string> = {
    [SourceFeature.SHOWS]: 'Shows',
    [SourceFeature.MOVIES]: 'Movies',
    [SourceFeature.MOVIE_EXTRAS]: 'Movie extras',
    [SourceFeature.BROWSE]: 'Browse',
    [SourceFeature.LOGIN]: 'Sign-in',
    [SourceFeature.LIVE_EPISODES]: 'Live episodes',
    [SourceFeature.MEMBERSHIP_LEVELS]: 'Membership levels',
    [SourceFeature.RSS_STREAMING]: 'RSS streaming',
    [SourceFeature.VIDEOS]: 'Single videos',
    [SourceFeature.EPISODE_LISTS]: 'Episode lists',
    [SourceFeature.SEARCH]: 'Search',
    [SourceFeature.QUICK_CHECK]: 'Quick checks',
}

// Features that are settings rather than kinds of content.
const SETTING_FEATURES: readonly string[] = [SourceFeature.PROGRAM_UPDATES, SourceFeature.COOKIES, SourceFeature.API_KEY]

function SourceCard({source, tabProps}: {source: SourceRead; tabProps: SettingsTabProps}) {
    const {SignIn, Settings} = sourceComponents(source.id)
    const parts = [
        sourceHas(source, SourceFeature.LOGIN) && SignIn ? <SignIn key="sign-in"/> : null,
        sourceHas(source, SourceFeature.PROGRAM_UPDATES) ? <SourceProgramCard key="program" source={source}/> : null,
        sourceHas(source, SourceFeature.COOKIES) ? <SourceCookiesCard key="cookies" source={source}/> : null,
        Settings ? <Settings key="settings" {...tabProps}/> : null,
    ].filter(Boolean)
    return (
        <SourceSection
            title={source.name}
            description={source.domains.includes('*') ? 'Many sites' : source.domains.join(', ')}
            summaryExtra={
                <span className="source-feature-list" role="list" aria-label={`What ${source.name} supports`}>
                    {source.features.filter((feature) => !SETTING_FEATURES.includes(feature)).map((feature) => (
                        <span key={feature} className="source-badge" role="listitem">{FEATURE_LABELS[feature] ?? feature}</span>
                    ))}
                </span>
            }
        >
            {parts.length ? parts : <p className="source-section__empty">{source.name} has nothing to set up.</p>}
        </SourceSection>
    )
}

export default function SourcesSettingsTab(tabProps: SettingsTabProps) {
    const {data: sources, isLoading, error} = useSources()
    if (isLoading) return <p>Loading sources…</p>
    if (error) return <div className="form-error-card" role="alert">Could not load sources: {error.message}</div>
    return (
        <div className="source-card-list">
            <p className="view-description">
                The services VODLoft can add media from. A link you paste on the Add media page goes to the Source that
                recognises it. Signing in is optional, and only needed for content that requires an account.
            </p>
            {(sources ?? []).map((source) => (
                <SourceCard key={source.id} source={source} tabProps={tabProps}/>
            ))}
            <SourceDomainsCard/>
        </div>
    )
}
