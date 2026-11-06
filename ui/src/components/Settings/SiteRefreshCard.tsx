import {zodResolver} from '@hookform/resolvers/zod'
import {useQueryClient} from '@tanstack/react-query'
import {Controller, useForm} from 'react-hook-form'
import toast from 'react-hot-toast'

import {saveSiteRefresh, useSiteRefresh} from '../../lib/queries'
import {
    SiteRefreshFormSchema,
    SiteRefreshModeReg,
    SiteRefreshReadSchema,
    type SiteRefreshFormIn,
    type SiteRefreshFormValues,
    type SiteRefreshRead,
} from '../../types/schemas/siteRefresh'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'
import NumberInput from '../common/NumberInput'
import SimpleSelect from '../common/SimpleSelect'

const PENDING_FIELDS = [
    {name: 'pendingUpcomingMinutes', label: 'Upcoming', help: 'every … minutes until 15 minutes before the start'},
    {name: 'pendingStartingMinutes', label: 'Starting', help: 'every … minutes around the start'},
    {name: 'pendingLiveMinutes', label: 'Live', help: 'every … minutes while live or being finished'},
] as const

function formValues(site: SiteRefreshRead): SiteRefreshFormIn {
    return {
        refreshMode: site.refreshMode,
        refreshIntervals: site.refreshIntervals ?? '',
        pendingChecks: site.pendingChecks,
        pendingUpcomingMinutes: site.pendingUpcomingMinutes,
        pendingStartingMinutes: site.pendingStartingMinutes,
        pendingLiveMinutes: site.pendingLiveMinutes,
    }
}

function SiteRefreshRow({site}: {site: SiteRefreshRead}) {
    const queryClient = useQueryClient()
    const form = useForm<SiteRefreshFormIn, unknown, SiteRefreshFormValues>({
        resolver: zodResolver(SiteRefreshFormSchema),
        defaultValues: formValues(site),
    })
    const {control, register, watch, formState: {errors, isDirty, isSubmitting}} = form
    const mode = watch('refreshMode')

    const submit = buildServerAwareSubmit<SiteRefreshFormIn, SiteRefreshFormValues>(
        form,
        (values) => saveSiteRefresh(site.key, values),
        {
            fallbackField: 'refreshIntervals',
            genericMessage: `Could not save the settings of ${site.name}`,
            rootOnFieldErrors: false,
            onSuccess: (result, {resetForm}) => {
                const saved = SiteRefreshReadSchema.parse(result)
                queryClient.setQueryData<SiteRefreshRead[]>(['siteRefresh'], (current) =>
                    current?.map((item) => (item.key === saved.key ? saved : item)))
                resetForm(formValues(saved))
                toast.success(`Saved the settings of ${site.name}`)
            },
        },
    )

    const pendingError = PENDING_FIELDS.map(({name}) => errors[name]?.message).find(Boolean)
    const error = errors.refreshIntervals?.message ?? pendingError ?? errors.root?.message
    return (
        <tr>
            <td>
                {site.name}
                {site.domains.length ? <span className="source-site-domains"> · {site.domains.join(', ')}</span> : null}
            </td>
            {site.refreshes || site.checksPending || site.followsPending ? (
                <td>
                    <form className="site-refresh-form" onSubmit={submit} noValidate>
                        {site.refreshes ? (
                            <Controller control={control} name="refreshMode" render={({field}) => (
                                <SimpleSelect
                                    aria-label={`Metadata refresh of ${site.name}`}
                                    registry={SiteRefreshModeReg}
                                    value={field.value}
                                    menuPlacement="auto"
                                    onChange={field.onChange}
                                />
                            )}/>
                        ) : null}
                        {site.checksPending ? (
                            <label className="site-refresh-pending">
                                <input type="checkbox" {...register('pendingChecks')}/>
                                <span>Upcoming and live videos</span>
                            </label>
                        ) : null}
                        {site.refreshes && mode === 'own' ? (
                            <input
                                className="input settings-input"
                                aria-label={`Refresh intervals of ${site.name}`}
                                placeholder="30m,2h,24h"
                                aria-invalid={Boolean(errors.refreshIntervals)}
                                {...register('refreshIntervals')}
                            />
                        ) : null}
                        {site.followsPending ? (
                            <fieldset className="site-refresh-rhythm">
                                <legend>Look upcoming and live episodes up</legend>
                                {PENDING_FIELDS.map(({name, label, help}) => (
                                    <label key={name} className="site-refresh-rhythm__field" title={help}>
                                        <span>{label}</span>
                                        <NumberInput
                                            inputMode="numeric" min={2} max={name === 'pendingUpcomingMinutes' ? 1440 : 60} step={1}
                                            aria-label={`${label}: ${help}, ${site.name}`}
                                            aria-invalid={Boolean(errors[name])}
                                            {...register(name, {valueAsNumber: true})}
                                        />
                                        <span>min</span>
                                    </label>
                                ))}
                            </fieldset>
                        ) : null}
                        <button type="submit" className="btn" disabled={!isDirty || isSubmitting}>
                            Save
                        </button>
                    </form>
                    {error ? <div className="error" role="alert">{error}</div> : null}
                </td>
            ) : (
                <td className="site-refresh-unsupported">Not supported by the Source of its collections and videos</td>
            )}
        </tr>
    )
}

/** Which schedule each Site's new uploads follow while VODLoft looks them up again. */
export default function SiteRefreshCard() {
    const {data: sites, error} = useSiteRefresh()
    return (
        <div className="settings-field settings-field--wide">
            <label>Metadata refresh and upcoming videos per Site</label>
            {error ? <p className="error" role="alert">Could not load the Sites: {error.message}</p> : null}
            {sites?.length ? (
                <table className="source-site-table site-refresh-table">
                    <thead>
                        <tr><th scope="col">Site</th><th scope="col">Settings</th></tr>
                    </thead>
                    <tbody>
                        {sites.map((site) => <SiteRefreshRow key={site.key} site={site}/>)}
                    </tbody>
                </table>
            ) : null}
            {sites && !sites.length ? <p className="settings-field__help">Sites show up here once you add a collection or video.</p> : null}
            <div className="settings-field__help">
                Each Site follows the system schedule above, a schedule of its own, or none. Only what VODLoft shows and
                serves in its feeds changes: downloaded files keep their names and metadata. With upcoming and live
                videos on, VODLoft adds a stream or premiere as soon as it is announced and follows it until it is
                published, then downloads it. It never records a stream while it is live. An upcoming episode is
                looked up every so many minutes, more often from 15 minutes before it starts until an hour after,
                and while it is live. An episode without a known start is looked up as if it were about to start.
            </div>
        </div>
    )
}
