import {zodResolver} from '@hookform/resolvers/zod'
import {useQueryClient} from '@tanstack/react-query'
import {useRef, useState} from 'react'
import {Controller, useForm, type Control} from 'react-hook-form'

import {saveSiteRefresh, useSiteRefresh} from '../../lib/queries'
import {
    SiteRefreshFormSchema,
    SiteRefreshModeReg,
    SiteRefreshReadSchema,
    SiteRhythmReg,
    SiteUpcomingReg,
    type SiteRefreshFormIn,
    type SiteRefreshFormValues,
    type SiteRefreshRead,
} from '../../types/schemas/siteRefresh'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'
import type {SelectRegistry} from '../../utils/selectRegistry'
import NumberInput from '../common/NumberInput'
import SimpleSelect from '../common/SimpleSelect'
import {useSettingsDraft} from './settingsDrafts'
import './SiteRefreshCard.css'

/** The system settings a Site follows unless it has its own, as the page's draft has them. */
export type SiteSystemSettings = {
    metadataRefreshIntervals: string
    upcomingAndLive: boolean
    pendingUpcomingMinutes: number
    pendingStartingMinutes: number
    pendingLiveMinutes: number
}

export const PENDING_FIELDS = [
    {name: 'pendingUpcomingMinutes', label: 'Upcoming', max: 24 * 60},
    {name: 'pendingStartingMinutes', label: 'Starting', max: 60},
    {name: 'pendingLiveMinutes', label: 'Live', max: 60},
] as const

const spaced = (intervals: string) => intervals.split(',').map((part) => part.trim()).join(', ')

function formValues(site: SiteRefreshRead, system: SiteSystemSettings): SiteRefreshFormIn {
    // A Site without its own lookup times starts from the system's, should it get its own.
    const own = site.pendingUpcomingMinutes !== null
    return {
        refreshMode: site.refreshMode,
        refreshIntervals: site.refreshIntervals ?? '',
        pendingChecks: site.pendingChecks === null ? 'system' : site.pendingChecks ? 'on' : 'off',
        pendingRhythm: own ? 'own' : 'system',
        pendingUpcomingMinutes: site.pendingUpcomingMinutes ?? system.pendingUpcomingMinutes,
        pendingStartingMinutes: site.pendingStartingMinutes ?? system.pendingStartingMinutes,
        pendingLiveMinutes: site.pendingLiveMinutes ?? system.pendingLiveMinutes,
    }
}

type BadgeTone = 'schedule' | 'on' | 'off'

function Badge({tone, children}: {tone: BadgeTone; children: string}) {
    return <span className={`site-refresh-badge site-refresh-badge--${tone}`}>{children}</span>
}

function SettingSelect<TName extends 'refreshMode' | 'pendingChecks' | 'pendingRhythm'>({control, name, registry, label}: {
    control: Control<SiteRefreshFormIn, unknown, SiteRefreshFormValues>
    name: TName
    registry: SelectRegistry
    label: string
}) {
    return (
        <div className="site-refresh-choice">
            <Controller control={control} name={name} render={({field}) => (
                <SimpleSelect
                    aria-label={label}
                    registry={registry}
                    value={field.value}
                    menuPlacement="auto"
                    onChange={field.onChange}
                />
            )}/>
        </div>
    )
}

function SiteRefreshRow({site, system}: {site: SiteRefreshRead; system: SiteSystemSettings}) {
    const queryClient = useQueryClient()
    const [open, setOpen] = useState(false)
    const saved = useRef(false)
    const form = useForm<SiteRefreshFormIn, unknown, SiteRefreshFormValues>({
        resolver: zodResolver(SiteRefreshFormSchema),
        defaultValues: formValues(site, system),
    })
    const {control, register, reset, watch, formState: {errors, dirtyFields}} = form
    const mode = watch('refreshMode')
    const upcoming = watch('pendingChecks')
    const rhythm = watch('pendingRhythm')
    const follows = upcoming === 'system' ? system.upcomingAndLive : upcoming === 'on'

    const submit = buildServerAwareSubmit<SiteRefreshFormIn, SiteRefreshFormValues>(
        form,
        (values) => saveSiteRefresh(site.key, values),
        {
            fallbackField: 'refreshIntervals',
            genericMessage: `Could not save the settings of ${site.name}`,
            rootOnFieldErrors: false,
            onSuccess: (result, {resetForm}) => {
                const savedSite = SiteRefreshReadSchema.parse(result)
                queryClient.setQueryData<SiteRefreshRead[]>(['siteRefresh'], (current) =>
                    current?.map((item) => (item.key === savedSite.key ? savedSite : item)))
                resetForm(formValues(savedSite, system))
                saved.current = true
            },
        },
    )

    useSettingsDraft(
        `site-refresh:${site.key}`,
        Object.keys(dirtyFields).length,
        async () => {
            saved.current = false
            await submit()
            if (!saved.current) setOpen(true)
            return saved.current
        },
        () => reset(formValues(site, system)),
    )

    const rhythmError = PENDING_FIELDS.map(({name}) => errors[name]?.message).find(Boolean)
    const scheduleError = errors.refreshIntervals?.message ?? errors.root?.message
    const systemMinutes = `${system.pendingUpcomingMinutes}, ${system.pendingStartingMinutes} and ${system.pendingLiveMinutes} minutes`

    return (
        <details className="site-refresh-site" open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
            <summary>
                <span className="site-refresh-site__name">
                    <strong>{site.name}</strong>
                    {site.domains.length ? <span>{site.domains.join(', ')}</span> : null}
                </span>
                <span className="site-refresh-site__badges">
                    {site.refreshes ? (
                        mode === 'own' ? <Badge tone="schedule">Own schedule</Badge>
                            : mode === 'system' ? <Badge tone="off">System schedule</Badge>
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
                                <SettingSelect control={control} name="refreshMode" registry={SiteRefreshModeReg}
                                               label={`Metadata refresh of ${site.name}`}/>
                                {mode === 'own' ? (
                                    <input
                                        className="input settings-input site-refresh-intervals"
                                        aria-label={`Refresh intervals of ${site.name}`}
                                        placeholder="30m, 2h, 24h"
                                        aria-invalid={Boolean(errors.refreshIntervals)}
                                        {...register('refreshIntervals')}
                                    />
                                ) : null}
                                {mode === 'system' ? <span className="site-refresh-inherited">{spaced(system.metadataRefreshIntervals)}</span> : null}
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
                                <SettingSelect control={control} name="pendingChecks" registry={SiteUpcomingReg}
                                               label={`Upcoming and live videos of ${site.name}`}/>
                                {upcoming === 'system' ? (
                                    <span className="site-refresh-inherited">{system.upcomingAndLive ? 'On' : 'Off'}</span>
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
                                <SettingSelect control={control} name="pendingRhythm" registry={SiteRhythmReg}
                                               label={`Lookup times of ${site.name}`}/>
                                {rhythm === 'system' ? <span className="site-refresh-inherited">{systemMinutes}</span> : null}
                            </div>
                            {rhythm === 'own' ? (
                                <div className="site-refresh-rhythm">
                                    {PENDING_FIELDS.map(({name, label, max}) => (
                                        <label key={name} className="site-refresh-rhythm__field">
                                            <span>{label}</span>
                                            <NumberInput
                                                inputMode="numeric" min={2} max={max} step={1}
                                                aria-label={`${label}, minutes between lookups, ${site.name}`}
                                                aria-invalid={Boolean(errors[name])}
                                                {...register(name, {valueAsNumber: true})}
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

/** Each Site VODLoft knows, following the system settings or its own. */
export default function SiteRefreshCard({system}: {system: SiteSystemSettings}) {
    const {data: sites, error} = useSiteRefresh()
    return (
        <div className="settings-field settings-field--wide site-refresh">
            <label>Sites</label>
            <div className="settings-field__help">
                Every Site follows the system settings above unless you give it its own. Some Sites start with a
                schedule of their own, such as The Daily Wire and YouTube.
            </div>
            {error ? <p className="error" role="alert">Could not load the Sites: {error.message}</p> : null}
            {sites?.length ? (
                <div className="site-refresh-sites">
                    {sites.map((site) => <SiteRefreshRow key={site.key} site={site} system={system}/>)}
                </div>
            ) : null}
            {sites && !sites.length ? <p className="settings-field__help">Sites show up here once you add a collection or video.</p> : null}
        </div>
    )
}
