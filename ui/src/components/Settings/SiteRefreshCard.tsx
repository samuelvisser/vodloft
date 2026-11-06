import {useState} from 'react'

import {useSiteRefresh} from '../../lib/queries'
import {SITE_REFRESH_OFF, type SettingsValues, type SiteSchedule} from '../../types/schemas/settings'
import {
    SiteRefreshModeReg,
    SiteRhythmReg,
    SiteUpcomingReg,
    type SiteRefreshRead,
} from '../../types/schemas/siteRefresh'
import type {SelectRegistry} from '../../utils/selectRegistry'
import NumberInput from '../common/NumberInput'
import SimpleSelect from '../common/SimpleSelect'
import type {SettingsTabProps} from './SettingsTabTypes'
import './SiteRefreshCard.css'

type SystemSettings = SettingsValues['newEpisodeSchedule']
type MinutesField = 'pendingUpcomingMinutes' | 'pendingStartingMinutes' | 'pendingLiveMinutes'

export const PENDING_FIELDS: readonly {name: MinutesField; label: string; max: number}[] = [
    {name: 'pendingUpcomingMinutes', label: 'Upcoming', max: 24 * 60},
    {name: 'pendingStartingMinutes', label: 'Starting', max: 60},
    {name: 'pendingLiveMinutes', label: 'Live', max: 60},
]

const UNSET: SiteSchedule = {
    metadataRefresh: null,
    upcomingAndLive: null,
    pendingUpcomingMinutes: null,
    pendingStartingMinutes: null,
    pendingLiveMinutes: null,
}

const spaced = (intervals: string) => intervals.split(',').map((part) => part.trim()).join(', ')

type BadgeTone = 'schedule' | 'on' | 'off'

function Badge({tone, children}: {tone: BadgeTone; children: string}) {
    return <span className={`site-refresh-badge site-refresh-badge--${tone}`}>{children}</span>
}

function SettingSelect({registry, label, value, onChange}: {
    registry: SelectRegistry
    label: string
    value: string
    onChange: (value: string) => void
}) {
    return (
        <div className="site-refresh-choice">
            <SimpleSelect aria-label={label} registry={registry} value={value} menuPlacement="auto" onChange={onChange}/>
        </div>
    )
}

type RowProps = Pick<SettingsTabProps, 'updateDraft' | 'errorFor'> & {
    site: SiteRefreshRead
    own: SiteSchedule
    system: SystemSettings
}

function SiteRefreshRow({site, own, system, updateDraft, errorFor}: RowProps) {
    const [open, setOpen] = useState(false)
    const change = (values: Partial<SiteSchedule>) => updateDraft((next) => {
        next.siteSchedules = {...next.siteSchedules, [site.key]: {...UNSET, ...next.siteSchedules[site.key], ...values}}
    })

    const defaultRefresh = site.defaultRefreshIntervals ?? system.metadataRefreshIntervals
    const mode = own.metadataRefresh === null ? 'default' : own.metadataRefresh === SITE_REFRESH_OFF ? 'off' : 'own'
    const upcoming = own.upcomingAndLive === null ? 'default' : own.upcomingAndLive ? 'on' : 'off'
    const follows = own.upcomingAndLive ?? system.upcomingAndLive
    const rhythm = own.pendingUpcomingMinutes === null ? 'default' : 'own'

    const error = (field: keyof SiteSchedule) => errorFor(`siteSchedules.${site.key}.${field}`)
    const scheduleError = error('metadataRefresh')
    const rhythmError = PENDING_FIELDS.map(({name}) => error(name)).find(Boolean)
    // An error opens the Site, so a refused save shows why.
    const isOpen = open || Boolean(scheduleError || rhythmError)
    const systemMinutes = `${system.pendingUpcomingMinutes}, ${system.pendingStartingMinutes} and ${system.pendingLiveMinutes} minutes`

    return (
        <details className="site-refresh-site" open={isOpen} onToggle={(event) => setOpen(event.currentTarget.open)}>
            <summary>
                <span className="site-refresh-site__name">
                    <strong>{site.name}</strong>
                    {site.domains.length ? <span>{site.domains.join(', ')}</span> : null}
                </span>
                <span className="site-refresh-site__badges">
                    {site.refreshes ? (
                        mode === 'own' ? <Badge tone="schedule">Own schedule</Badge>
                            : mode === 'default' ? <Badge tone="off">Default schedule</Badge>
                                : <Badge tone="off">No metadata refresh</Badge>
                    ) : null}
                    {site.followsPending ? (
                        follows ? <Badge tone="on">Upcoming and live</Badge> : <Badge tone="off">No upcoming</Badge>
                    ) : null}
                    {!site.refreshes && !site.followsPending ? <Badge tone="off">Nothing to set</Badge> : null}
                </span>
            </summary>
            <div className="site-refresh-site__body">
                {site.refreshes ? (
                    <div className="site-refresh-setting">
                        <span className="site-refresh-setting__label">Metadata refresh</span>
                        <div className="site-refresh-setting__control">
                            <div className="site-refresh-setting__line">
                                <SettingSelect
                                    registry={SiteRefreshModeReg}
                                    label={`Metadata refresh of ${site.name}`}
                                    value={mode}
                                    onChange={(value) => change({
                                        // An own schedule starts from the one the Site follows now.
                                        metadataRefresh: value === 'default' ? null : value === 'off' ? SITE_REFRESH_OFF : defaultRefresh,
                                    })}
                                />
                                {mode === 'own' ? (
                                    <input
                                        className="input settings-input site-refresh-intervals"
                                        aria-label={`Refresh intervals of ${site.name}`}
                                        placeholder="30m, 2h, 24h"
                                        aria-invalid={Boolean(scheduleError)}
                                        value={own.metadataRefresh ?? ''}
                                        onChange={(event) => change({metadataRefresh: event.target.value})}
                                    />
                                ) : null}
                                {mode === 'default' ? (
                                    <span className="site-refresh-inherited">
                                        {spaced(defaultRefresh)}
                                        {site.defaultRefreshIntervals ? ` (${site.name}'s own)` : ' (system setting)'}
                                    </span>
                                ) : null}
                            </div>
                            {scheduleError ? <div className="error" role="alert">{scheduleError}</div> : null}
                        </div>
                    </div>
                ) : null}
                {site.followsPending ? (
                    <div className="site-refresh-setting">
                        <span className="site-refresh-setting__label">Upcoming and live</span>
                        <div className="site-refresh-setting__control">
                            <div className="site-refresh-setting__line">
                                <SettingSelect
                                    registry={SiteUpcomingReg}
                                    label={`Upcoming and live videos of ${site.name}`}
                                    value={upcoming}
                                    onChange={(value) => change({upcomingAndLive: value === 'default' ? null : value === 'on'})}
                                />
                                {upcoming === 'default' ? (
                                    <span className="site-refresh-inherited">{system.upcomingAndLive ? 'On' : 'Off'} (system setting)</span>
                                ) : null}
                            </div>
                        </div>
                    </div>
                ) : null}
                {site.followsPending && follows ? (
                    <div className="site-refresh-setting">
                        <span className="site-refresh-setting__label">Look them up every</span>
                        <div className="site-refresh-setting__control">
                            <div className="site-refresh-setting__line">
                                <SettingSelect
                                    registry={SiteRhythmReg}
                                    label={`Lookup times of ${site.name}`}
                                    value={rhythm}
                                    // Own times start from the system's.
                                    onChange={(value) => change(Object.fromEntries(PENDING_FIELDS.map(({name}) => (
                                        [name, value === 'default' ? null : system[name]]
                                    ))))}
                                />
                                {rhythm === 'default' ? <span className="site-refresh-inherited">{systemMinutes} (system setting)</span> : null}
                            </div>
                            {rhythm === 'own' ? (
                                <div className="site-refresh-rhythm">
                                    {PENDING_FIELDS.map(({name, label, max}) => (
                                        <label key={name} className="site-refresh-rhythm__field">
                                            <span>{label}</span>
                                            <NumberInput
                                                inputMode="numeric" min={2} max={max} step={1}
                                                aria-label={`${label}, minutes between lookups, ${site.name}`}
                                                aria-invalid={Boolean(error(name))}
                                                value={Number.isFinite(own[name]) ? String(own[name]) : ''}
                                                onChange={(event) => change({[name]: event.target.valueAsNumber})}
                                            />
                                            <span>min</span>
                                        </label>
                                    ))}
                                </div>
                            ) : null}
                            {rhythmError ? <div className="error" role="alert">{rhythmError}</div> : null}
                        </div>
                    </div>
                ) : null}
                {!site.refreshes && !site.followsPending ? (
                    <p className="settings-field__help">The Sources of this Site's collections and videos have nothing to set here.</p>
                ) : null}
            </div>
        </details>
    )
}

/** Each Site VODLoft knows, following its defaults or settings of its own under siteSchedules in config.yml. */
export default function SiteRefreshCard({draft, updateDraft, errorFor}: Pick<SettingsTabProps, 'draft' | 'updateDraft' | 'errorFor'>) {
    const {data: sites, error} = useSiteRefresh()
    return (
        <div className="settings-field settings-field--wide site-refresh">
            <label>Sites</label>
            <div className="settings-field__help">
                Every Site follows its default unless you give it settings of its own. The default is the system
                setting above, except for Sites with a schedule of their own, such as The Daily Wire and YouTube.
            </div>
            {error ? <p className="error" role="alert">Could not load the Sites: {error.message}</p> : null}
            {sites?.length ? (
                <div className="site-refresh-sites">
                    {sites.map((site) => (
                        <SiteRefreshRow
                            key={site.key}
                            site={site}
                            own={{...UNSET, ...draft.siteSchedules[site.key]}}
                            system={draft.newEpisodeSchedule}
                            updateDraft={updateDraft}
                            errorFor={errorFor}
                        />
                    ))}
                </div>
            ) : null}
            {sites && !sites.length ? <p className="settings-field__help">Sites show up here once you add a collection or video.</p> : null}
        </div>
    )
}
