import {useSources} from '../../lib/queries'
import {SourceFeature, SourceRead, sourceHas} from '../../types/schemas/source'
import SourceCookiesCard from '../Source/SourceCookiesCard'
import SourceProgramCard from '../Source/SourceProgramCard'
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
}

// Features that are settings rather than kinds of content.
const SETTING_FEATURES: readonly string[] = [SourceFeature.PROGRAM_UPDATES, SourceFeature.COOKIES]

function SourceCard({source, tabProps}: {source: SourceRead; tabProps: SettingsTabProps}) {
    const {SignIn, Settings} = sourceComponents(source.id)
    return (
        <section className="card source-card" aria-labelledby={`source-${source.id}-title`}>
            <div className="card-body">
                <div className="source-card-header">
                    <h3 id={`source-${source.id}-title`}>{source.name}</h3>
                    <span className="source-card-domains">
                        {source.domains.includes('*') ? 'Many sites' : source.domains.join(', ')}
                    </span>
                </div>
                <ul className="source-feature-list" aria-label={`What ${source.name} supports`}>
                    {source.features.filter((feature) => !SETTING_FEATURES.includes(feature)).map((feature) => (
                        <li key={feature} className="source-badge">{FEATURE_LABELS[feature] ?? feature}</li>
                    ))}
                </ul>
            </div>
            {sourceHas(source, SourceFeature.LOGIN) && SignIn ? <SignIn/> : null}
            {sourceHas(source, SourceFeature.PROGRAM_UPDATES) ? <SourceProgramCard source={source}/> : null}
            {sourceHas(source, SourceFeature.COOKIES) ? <SourceCookiesCard source={source}/> : null}
            {Settings ? <Settings {...tabProps}/> : null}
        </section>
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
        </div>
    )
}
