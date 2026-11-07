import {useState, type ReactNode} from 'react'
import Switch from 'react-switch'

import {useSitesSettings} from '../../lib/queries'
import type {UpgradeImprovement} from '../../types/schemas/download_profile'
import {
    SITE_REFRESH_OFF,
    SITE_SETTING_DEFAULT,
    type LookupMinutes,
    type SettingsValues,
    type SiteSettingKey,
    type SiteSettingValues,
} from '../../types/schemas/settings'
import {
    SiteRefreshModeReg,
    SiteToggleModeReg,
    SiteValueModeReg,
    type OfferedSetting,
    type SiteSettingGroup,
    type SiteSettingsRead,
    UPGRADE_IMPROVEMENT_LABELS,
    UpgradeRepeatReg,
} from '../../types/schemas/siteSettings'
import {AutoSubtitlesReg} from '../../types/quality'
import {SponsorBlockActionReg, SponsorBlockCategoryReg} from '../../types/sponsorblock'
import type {SelectRegistry} from '../../utils/selectRegistry'
import NumberInput from '../common/NumberInput'
import SimpleSelect from '../common/SimpleSelect'
import type {SettingsTabProps} from './SettingsTabTypes'
import './SiteSettingsCard.css'

/** Checkboxes for what counts as a better version, of the improvements given. */
export function ImprovementChoices({offered, value, onChange, idPrefix}: {
    offered: readonly UpgradeImprovement[]
    value: readonly UpgradeImprovement[]
    onChange: (value: UpgradeImprovement[]) => void
    idPrefix: string
}) {
    return (
        <span className="site-settings-checks">
            {offered.map((improvement) => (
                <label key={improvement} className="site-settings-check" htmlFor={`${idPrefix}-${improvement}`}>
                    <input
                        id={`${idPrefix}-${improvement}`}
                        type="checkbox"
                        checked={value.includes(improvement)}
                        onChange={(event) => onChange(offered.filter((key) => (
                            key === improvement ? event.target.checked : value.includes(key)
                        )))}
                    />
                    {UPGRADE_IMPROVEMENT_LABELS[improvement]}
                </label>
            ))}
        </span>
    )
}

type ControlProps = {
    value: any
    onChange: (value: any) => void
    site: SiteSettingsRead
    label: string
    invalid: boolean
}

type Definition = {
    label: string
    /** toggle: on or off; refresh: a schedule or off; value: anything else. */
    kind: 'toggle' | 'refresh' | 'value'
    /** The system default, for a setting that has one. */
    system?: (draft: SettingsValues) => unknown
    summary: (value: any, site: SiteSettingsRead) => string
    control?: (props: ControlProps) => ReactNode
    /** Shown only while this setting is on for the Site. */
    shownWhen?: SiteSettingKey
}

const spaced = (intervals: string) => intervals.split(',').map((part) => part.trim()).join(', ')
const onOff = (value: boolean) => value ? 'On' : 'Off'

function NumberControl({value, onChange, label, invalid, min, max, unit}: ControlProps & {min: number; max: number; unit: string}) {
    return (
        <span className="site-settings-number">
            <NumberInput
                inputMode="numeric" min={min} max={max} step={1} aria-label={label} aria-invalid={invalid}
                value={Number.isFinite(value) ? String(value) : ''}
                onChange={(event) => onChange(event.target.value === '' ? Number.NaN : event.target.valueAsNumber)}
            />
            <span>{unit}</span>
        </span>
    )
}

function SelectControl({value, onChange, label, registry}: ControlProps & {registry: SelectRegistry}) {
    return (
        <div className="site-settings-choice">
            <SimpleSelect aria-label={label} registry={registry} value={value} menuPlacement="auto" onChange={onChange}/>
        </div>
    )
}

const LOOKUP_FIELDS: readonly {name: keyof LookupMinutes; label: string; max: number}[] = [
    {name: 'upcoming', label: 'Upcoming', max: 24 * 60},
    {name: 'starting', label: 'Starting', max: 60},
    {name: 'live', label: 'Live', max: 60},
]

/** How each setting a Site can have of its own looks. Which settings a Site shows comes from the backend. */
const DEFINITIONS: Record<SiteSettingKey, Definition> = {
    metadataRefresh: {
        label: 'Metadata refresh',
        kind: 'refresh',
        system: (draft) => draft.newEpisodeSchedule.metadataRefreshIntervals,
        summary: (value: string) => value === SITE_REFRESH_OFF ? 'Off' : spaced(value),
        control: ({value, onChange, label, invalid}) => (
            <input
                className="input settings-input site-settings-intervals" aria-label={label} placeholder="30m, 2h, 24h"
                aria-invalid={invalid} value={value ?? ''} onChange={(event) => onChange(event.target.value)}
            />
        ),
    },
    upcomingAndLive: {
        label: 'Upcoming and live',
        kind: 'toggle',
        system: (draft) => draft.newEpisodeSchedule.upcomingAndLive,
        summary: onOff,
    },
    lookupMinutes: {
        label: 'Look them up every',
        kind: 'value',
        shownWhen: 'upcomingAndLive',
        system: (draft) => ({
            upcoming: draft.newEpisodeSchedule.pendingUpcomingMinutes,
            starting: draft.newEpisodeSchedule.pendingStartingMinutes,
            live: draft.newEpisodeSchedule.pendingLiveMinutes,
        }),
        summary: (value: LookupMinutes) => `${value.upcoming}, ${value.starting} and ${value.live} minutes`,
        control: ({value, onChange, label}) => (
            <div className="site-settings-rhythm">
                {LOOKUP_FIELDS.map(({name, label: field, max}) => (
                    <label key={name} className="site-settings-rhythm__field">
                        <span>{field}</span>
                        <NumberInput
                            inputMode="numeric" min={2} max={max} step={1} aria-label={`${field}, ${label}`}
                            value={Number.isFinite(value[name]) ? String(value[name]) : ''}
                            onChange={(event) => onChange({...value, [name]: event.target.valueAsNumber})}
                        />
                        <span>min</span>
                    </label>
                ))}
            </div>
        ),
    },
    downloadWithCountdown: {
        label: 'Download with countdown',
        kind: 'toggle',
        summary: onOff,
    },
    upgradeCheck: {
        label: 'Upgrade check',
        kind: 'toggle',
        system: (draft) => draft.downloadProfileDefaults.upgradeCheck,
        summary: onOff,
    },
    upgradeAfterDays: {
        label: 'Check after',
        kind: 'value',
        shownWhen: 'upgradeCheck',
        system: (draft) => draft.downloadProfileDefaults.upgradeAfterDays,
        summary: (value: number) => `${value} ${value === 1 ? 'day' : 'days'}`,
        control: (props) => <NumberControl {...props} min={1} max={365} unit="days"/>,
    },
    upgradeRepeat: {
        label: 'How often',
        kind: 'value',
        shownWhen: 'upgradeCheck',
        system: (draft) => draft.downloadProfileDefaults.upgradeRepeat,
        summary: (value: string) => UpgradeRepeatReg.getLabelLoose(value),
        control: (props) => <SelectControl {...props} registry={UpgradeRepeatReg}/>,
    },
    upgradeImprovements: {
        label: 'Better means',
        kind: 'value',
        shownWhen: 'upgradeCheck',
        system: (draft) => draft.downloadProfileDefaults.upgradeImprovements,
        summary: (value: UpgradeImprovement[], site) => {
            const chosen = site.upgradeImprovements.filter((improvement) => value.includes(improvement))
            return chosen.length ? chosen.map((improvement) => UPGRADE_IMPROVEMENT_LABELS[improvement]).join(', ') : 'Nothing'
        },
        control: ({value, onChange, site, label}) => (
            <ImprovementChoices offered={site.upgradeImprovements} value={value} onChange={onChange} idPrefix={label}/>
        ),
    },
    upgradeLengthMinutes: {
        label: 'Different length by',
        kind: 'value',
        shownWhen: 'upgradeCheck',
        system: (draft) => draft.downloadProfileDefaults.upgradeLengthMinutes,
        summary: (value: number) => `${value} minutes`,
        control: (props) => <NumberControl {...props} min={1} max={600} unit="minutes"/>,
    },
    autoSubtitles: {
        label: 'Auto-generated subtitles',
        kind: 'value',
        system: (draft) => draft.downloadProfileDefaults.autoSubtitles,
        summary: (value: string) => AutoSubtitlesReg.getLabelLoose(value),
        control: (props) => <SelectControl {...props} registry={AutoSubtitlesReg}/>,
    },
    sponsorblock: {
        label: 'SponsorBlock',
        kind: 'toggle',
        summary: onOff,
    },
    sponsorblockSegments: {
        label: 'SponsorBlock segments',
        kind: 'value',
        shownWhen: 'sponsorblock',
        summary: () => '',
        control: ({value, onChange, label}) => (
            <div className="site-settings-segments">
                {SponsorBlockCategoryReg.values.map((category) => (
                    <div key={category} className="site-settings-segment">
                        <span title={SponsorBlockCategoryReg.getHelp(category)}>{SponsorBlockCategoryReg.getLabel(category)}</span>
                        <SimpleSelect
                            aria-label={`${SponsorBlockCategoryReg.getLabel(category)}, ${label}`}
                            registry={SponsorBlockActionReg} value={value[category]} menuPlacement="auto"
                            onChange={(action) => onChange({...value, [category]: action})}
                        />
                    </div>
                ))}
            </div>
        ),
    },
}

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)

type Resolved = {
    offered: OfferedSetting
    definition: Definition
    /** The value the Site follows now. */
    value: any
    /** The Site has a value of its own, its preset included. */
    own: boolean
    /** The value is still the Site's preset. */
    isPreset: boolean
    system: unknown
}

function resolve(offered: OfferedSetting, values: SiteSettingValues, draft: SettingsValues): Resolved {
    const definition = DEFINITIONS[offered.key as SiteSettingKey]
    const system = definition.system?.(draft)
    const saved = values[offered.key as SiteSettingKey]
    let value: unknown
    if (saved === SITE_SETTING_DEFAULT) value = system
    else if (saved != null) value = saved
    else if (offered.start != null) value = offered.start
    else value = system
    const own = !definition.system || (saved != null && saved !== SITE_SETTING_DEFAULT) || (saved == null && offered.preset)
    return {offered, definition, value, own, isPreset: offered.preset && own && same(value, offered.start), system}
}

type BadgeTone = 'own' | 'on' | 'off'

function Badge({tone, children}: {tone: BadgeTone; children: string}) {
    return <span className={`site-settings-badge site-settings-badge--${tone}`}>{children}</span>
}

function badges(group: SiteSettingGroup, settings: Resolved[]): ReactNode[] {
    if (!settings.length) return [<Badge key="none" tone="off">Nothing to set</Badge>]
    const own = settings.some((setting) => setting.definition.system && setting.own)
    const found = (key: SiteSettingKey) => settings.find((setting) => setting.offered.key === key)
    const shown: ReactNode[] = [own
        ? <Badge key="own" tone="own">{group === 'scheduling' ? 'Own schedule' : 'Own settings'}</Badge>
        : <Badge key="own" tone="off">Defaults</Badge>]
    const switched = group === 'scheduling'
        ? found('upcomingAndLive') && [found('upcomingAndLive')!.value, 'Upcoming and live', 'No upcoming'] as const
        : found('upgradeCheck') && [found('upgradeCheck')!.value, 'Upgrade check on', 'No upgrade check'] as const
    if (switched) {
        shown.push(switched[0]
            ? <Badge key="switch" tone="on">{switched[1]}</Badge>
            : <Badge key="switch" tone="off">{switched[2]}</Badge>)
    }
    return shown
}

type RowProps = Pick<SettingsTabProps, 'updateDraft' | 'errorFor'> & {
    site: SiteSettingsRead
    group: SiteSettingGroup
    groupKeys: ReadonlySet<string>
    draft: SettingsValues
}

function SiteSettingsRow({site, group, groupKeys, draft, updateDraft, errorFor}: RowProps) {
    const [open, setOpen] = useState(false)
    const values = draft.siteSettings[site.key] ?? {}
    const all = site.settings.map((offered) => resolve(offered, values, draft))
    const settings = all.filter((setting) => groupKeys.has(setting.offered.key))
    const shown = settings.filter(({definition}) => (
        !definition.shownWhen || all.find((setting) => setting.offered.key === definition.shownWhen)?.value !== false
    ))
    const change = (key: string, value: unknown) => updateDraft((next) => {
        next.siteSettings = {...next.siteSettings, [site.key]: {...next.siteSettings[site.key], [key]: value}}
    })
    const errors = shown.map(({offered}) => errorFor(`siteSettings.${site.key}.${offered.key}`)
        ?? LOOKUP_FIELDS.map(({name}) => errorFor(`siteSettings.${site.key}.${offered.key}.${name}`)).find(Boolean))
    // An error opens the Site, so a refused save shows why.
    const isOpen = open || errors.some(Boolean)

    return (
        <details className="site-settings-site" open={isOpen} onToggle={(event) => setOpen(event.currentTarget.open)}>
            <summary>
                <span className="site-settings-site__name">
                    <strong>{site.name}</strong>
                    {site.domains.length ? <span>{site.domains.join(', ')}</span> : null}
                </span>
                <span className="site-settings-site__badges">{badges(group, settings)}</span>
            </summary>
            <div className="site-settings-site__body">
                {shown.map((setting, index) => (
                    <SettingRow
                        key={setting.offered.key} site={site} setting={setting} error={errors[index]}
                        onChange={(value) => change(setting.offered.key, value)}
                    />
                ))}
                {!shown.length ? (
                    <p className="settings-field__help">This Site has nothing to set here.</p>
                ) : null}
            </div>
        </details>
    )
}

function SettingRow({site, setting, error, onChange}: {
    site: SiteSettingsRead
    setting: Resolved
    error?: string
    onChange: (value: unknown) => void
}) {
    const {offered, definition, value, own, isPreset, system} = setting
    const label = `${definition.label} of ${site.name}`
    const modeLabel = `${label}: default or its own`
    // Back to the system default: a Site with a preset says so, any other one just leaves the setting out.
    const toDefault = () => onChange(offered.preset ? SITE_SETTING_DEFAULT : null)
    const fresh = () => structuredClone(offered.preset && offered.start !== SITE_REFRESH_OFF ? offered.start : system)

    let choice: ReactNode = null
    if (definition.system && definition.kind === 'toggle') {
        choice = (
            <SelectControl
                value={own ? (value ? 'on' : 'off') : 'default'} label={modeLabel} site={site} invalid={false}
                registry={SiteToggleModeReg}
                onChange={(mode: string) => mode === 'default' ? toDefault() : onChange(mode === 'on')}
            />
        )
    } else if (definition.system && definition.kind === 'refresh') {
        choice = (
            <SelectControl
                value={!own ? 'default' : value === SITE_REFRESH_OFF ? 'off' : 'own'} label={modeLabel} site={site} invalid={false}
                registry={SiteRefreshModeReg}
                onChange={(mode: string) => mode === 'default' ? toDefault() : onChange(mode === 'off' ? SITE_REFRESH_OFF : fresh())}
            />
        )
    } else if (definition.system) {
        choice = (
            <SelectControl
                value={own ? 'own' : 'default'} label={modeLabel} site={site} invalid={false} registry={SiteValueModeReg}
                onChange={(mode: string) => mode === 'default' ? toDefault() : onChange(fresh())}
            />
        )
    } else if (definition.kind === 'toggle') {
        choice = (
            <Switch
                checked={Boolean(value)} onChange={(checked) => onChange(checked)} aria-label={label}
                onColor="#0ea5e9" offColor="#94a3b8" uncheckedIcon={false} checkedIcon={false}
            />
        )
    }

    const editing = own && definition.control && !(definition.kind === 'refresh' && value === SITE_REFRESH_OFF)
    return (
        <div className="site-settings-setting">
            <span className="site-settings-setting__label">{definition.label}</span>
            <div className="site-settings-setting__control">
                <div className="site-settings-setting__line">
                    {choice}
                    {editing ? definition.control!({value, onChange, site, label, invalid: Boolean(error)}) : null}
                    {!own ? (
                        <span className="site-settings-inherited">
                            <b>{definition.summary(value, site)}</b> (system default)
                        </span>
                    ) : null}
                    {isPreset ? <span className="site-settings-preset">{site.name}'s preset</span> : null}
                </div>
                {error ? <div className="error" role="alert">{error}</div> : null}
            </div>
        </div>
    )
}

/** Every Site VODLoft knows, with the settings of the group it shows, under siteSettings in config.yml. */
export default function SiteSettingsCard({group, draft, updateDraft, errorFor, help}: Pick<SettingsTabProps, 'draft' | 'updateDraft' | 'errorFor'> & {
    group: SiteSettingGroup
    help: ReactNode
}) {
    const {data, error} = useSitesSettings()
    const groupKeys = new Set(data?.specs.filter((spec) => spec.group === group).map((spec) => spec.key))
    return (
        <div className="settings-field settings-field--wide site-settings">
            <label>Sites</label>
            <div className="settings-field__help">{help}</div>
            {error ? <p className="error" role="alert">Could not load the Sites: {error.message}</p> : null}
            {data?.sites.length ? (
                <div className="site-settings-sites">
                    {data.sites.map((site) => (
                        <SiteSettingsRow
                            key={site.key} site={site} group={group} groupKeys={groupKeys} draft={draft}
                            updateDraft={updateDraft} errorFor={errorFor}
                        />
                    ))}
                </div>
            ) : null}
            {data && !data.sites.length ? <p className="settings-field__help">Sites show up here once you add a collection or video.</p> : null}
        </div>
    )
}
