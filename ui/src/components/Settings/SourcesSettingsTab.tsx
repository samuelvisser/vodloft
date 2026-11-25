import {useSources} from '../../lib/queries'
import {ANY_DOMAIN, SourceFeature, SourceRead, sourceHas, sourceShown} from '../../types/schemas/source'
import SiteAuthenticationCard from '../Source/SiteAuthenticationCard'
import SourceSitesCard from '../Source/SourceSitesCard'
import SourceProgramCard from '../Source/SourceProgramCard'
import SourceSection from '../Source/SourceSection'
import SourceYtdlpOptionsCard from '../Source/SourceYtdlpOptionsCard'
import {sourceComponents} from '../Source/sourceComponents'
import type {SettingsTabProps} from './SettingsTabTypes'

const FEATURE_LABELS: Record<string, string> = {
    [SourceFeature.COLLECTIONS]: 'Collections',
    [SourceFeature.MOVIES]: 'Movies',
    [SourceFeature.MOVIE_EXTRAS]: 'Movie extras',
    [SourceFeature.BROWSE]: 'Browse',
    [SourceFeature.LOGIN]: 'Sign-in',
    [SourceFeature.LIVE_EPISODES]: 'Live episodes',
    [SourceFeature.MEMBERSHIP_LEVELS]: 'Membership levels',
    [SourceFeature.VIDEOS]: 'Single videos',
    [SourceFeature.EPISODE_LISTS]: 'Episode lists',
    [SourceFeature.SEARCH]: 'Search',
    [SourceFeature.QUICK_CHECK]: 'Quick checks',
    [SourceFeature.CATALOGUE_REFRESH]: 'Daily refresh',
    format_choices: 'Quality choices',
}

// Features that are settings or details rather than kinds of content.
const SETTING_FEATURES: readonly string[] = [
    SourceFeature.PROGRAM_UPDATES, SourceFeature.COOKIES, SourceFeature.API_KEY, SourceFeature.YTDLP_OPTIONS,
    SourceFeature.EPISODE_LOOKUPS, SourceFeature.PAGE_STREAMS, SourceFeature.OWN_STUDIO,
]

function SourceCard({source, tabProps}: {source: SourceRead; tabProps: SettingsTabProps}) {
    const {Settings} = sourceComponents(source.id)
    const parts = [
        sourceHas(source, SourceFeature.PROGRAM_UPDATES) ? <SourceProgramCard key="program" source={source}/> : null,
        Settings ? <Settings key="settings" {...tabProps}/> : null,
        sourceHas(source, SourceFeature.YTDLP_OPTIONS) ? <SourceYtdlpOptionsCard key="ytdlp-options" source={source}/> : null,
    ].filter(Boolean)
    // A Source with nothing to set is left out; what it supports shows on the Add media page.
    if (!parts.length) return null
    return (
        <SourceSection
            title={source.name}
            description={source.domains.includes(ANY_DOMAIN) ? 'Many sites' : source.domains.join(', ')}
            summaryExtra={
                <span className="source-feature-list" role="list" aria-label={`What ${source.name} supports`}>
                    {source.features.filter((feature) => !SETTING_FEATURES.includes(feature)).map((feature) => (
                        <span key={feature} className="source-badge" role="listitem">{FEATURE_LABELS[feature] ?? feature}</span>
                    ))}
                </span>
            }
        >
            {parts}
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
                The sites VODLoft can add media from. Signing in and API keys are optional, and set up per site under
                Authentication. Below that are the settings of each Source, the part of VODLoft that fetches from a site.
            </p>
            <SiteAuthenticationCard/>
            {(sources ?? []).filter(sourceShown).map((source) => (
                <SourceCard key={source.id} source={source} tabProps={tabProps}/>
            ))}
            <SourceSitesCard/>
        </div>
    )
}
