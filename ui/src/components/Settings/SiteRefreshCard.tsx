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
import SimpleSelect from '../common/SimpleSelect'

function SiteRefreshRow({site}: {site: SiteRefreshRead}) {
    const queryClient = useQueryClient()
    const form = useForm<SiteRefreshFormIn, unknown, SiteRefreshFormValues>({
        resolver: zodResolver(SiteRefreshFormSchema),
        defaultValues: {refreshMode: site.refreshMode, refreshIntervals: site.refreshIntervals ?? ''},
    })
    const {control, register, watch, formState: {errors, isDirty, isSubmitting}} = form
    const mode = watch('refreshMode')

    const submit = buildServerAwareSubmit<SiteRefreshFormIn, SiteRefreshFormValues>(
        form,
        (values) => saveSiteRefresh(site.key, values),
        {
            fallbackField: 'refreshIntervals',
            genericMessage: `Could not save the schedule of ${site.name}`,
            rootOnFieldErrors: false,
            onSuccess: (result, {resetForm}) => {
                const saved = SiteRefreshReadSchema.parse(result)
                queryClient.setQueryData<SiteRefreshRead[]>(['siteRefresh'], (current) =>
                    current?.map((item) => (item.key === saved.key ? saved : item)))
                resetForm({refreshMode: saved.refreshMode, refreshIntervals: saved.refreshIntervals ?? ''})
                toast.success(`Saved the schedule of ${site.name}`)
            },
        },
    )

    const error = errors.refreshIntervals?.message ?? errors.root?.message
    return (
        <tr>
            <td>
                {site.name}
                {site.domains.length ? <span className="source-site-domains"> · {site.domains.join(', ')}</span> : null}
            </td>
            {site.refreshes ? (
                <td>
                    <form className="site-refresh-form" onSubmit={submit} noValidate>
                        <Controller control={control} name="refreshMode" render={({field}) => (
                            <SimpleSelect
                                aria-label={`Metadata refresh of ${site.name}`}
                                registry={SiteRefreshModeReg}
                                value={field.value}
                                menuPlacement="auto"
                                onChange={field.onChange}
                            />
                        )}/>
                        {mode === 'own' ? (
                            <input
                                className="input settings-input"
                                aria-label={`Refresh intervals of ${site.name}`}
                                placeholder="30m,2h,24h"
                                aria-invalid={Boolean(errors.refreshIntervals)}
                                {...register('refreshIntervals')}
                            />
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
            <label>Metadata refresh per Site</label>
            {error ? <p className="error" role="alert">Could not load the Sites: {error.message}</p> : null}
            {sites?.length ? (
                <table className="source-site-table site-refresh-table">
                    <thead>
                        <tr><th scope="col">Site</th><th scope="col">Schedule</th></tr>
                    </thead>
                    <tbody>
                        {sites.map((site) => <SiteRefreshRow key={site.key} site={site}/>)}
                    </tbody>
                </table>
            ) : null}
            {sites && !sites.length ? <p className="settings-field__help">Sites show up here once you add a collection or video.</p> : null}
            <div className="settings-field__help">
                Each Site follows the system schedule above, a schedule of its own, or none. Only what VODLoft shows and
                serves in its feeds changes: downloaded files keep their names and metadata.
            </div>
        </div>
    )
}
