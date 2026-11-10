import {useEffect, useMemo, useRef} from 'react'
import {type UseFormReturn, useWatch} from 'react-hook-form'
import Select from 'react-select'

import {useLocalMediaProfileSites} from '../../lib/queries'
import {sitesForLocalMediaProfileType, takesUpcomingSites, type LocalMediaProfileType} from '../../types/local_media_profile'
import {createSelectRegistry} from '../../utils/selectRegistry'
import ReadMore from '../../utils/ReadMore'
import SelectAllLabel from '../common/SelectAllLabel'

const UPCOMING_SITES = '__upcoming__'

/** The Sites a profile is offered for, and whether Sites VODLoft sees later join them. A new profile starts with
 * every Site VODLoft knows and upcoming Sites. */
export default function LocalMediaProfileSitesField({form, mode}: {
    form: UseFormReturn<any>
    mode: LocalMediaProfileType
}) {
    const {control, setValue, getValues, formState: {errors}} = form
    const {data: sites} = useLocalMediaProfileSites()
    const [siteKeys, includeUpcomingSites] = useWatch({control, name: ['siteKeys', 'includeUpcomingSites']}) as [string[] | null, boolean]
    const available = useMemo(() => sitesForLocalMediaProfileType(sites, mode), [sites, mode])
    const upcoming = takesUpcomingSites(sites, mode)

    // A new profile starts with every Site VODLoft knows, again when the user picks another profile type.
    const startedFor = useRef<LocalMediaProfileType | null>(null)
    useEffect(() => {
        if (!sites) return
        const isNew = getValues('id') == null
        if (getValues('siteKeys') == null || (isNew && startedFor.current !== null && startedFor.current !== mode)) {
            setValue('siteKeys', available.map((site) => site.key), {shouldDirty: false})
        }
        startedFor.current = mode
    }, [sites, available, mode, getValues, setValue])

    const siteReg = useMemo(() => createSelectRegistry(
        'LocalMediaProfileSite',
        {
            ...(upcoming ? {[UPCOMING_SITES]: {label: 'Include upcoming sites'}} : {}),
            ...Object.fromEntries(available.map((site) => [site.key, {label: site.name}])),
        },
        [...(upcoming ? [UPCOMING_SITES] : []), ...available.map((site) => site.key)],
    ), [available, upcoming])

    // With one Site and nothing to come there is nothing to choose.
    if (!sites || siteReg.values.length < 2) return null

    const chosen = [...(upcoming && includeUpcomingSites ? [UPCOMING_SITES] : []), ...(siteKeys ?? [])]
    const error = errors.siteKeys ?? errors.includeUpcomingSites
    return (
        <div className="form-row">
            <SelectAllLabel
                htmlFor="mp-sites"
                allChosen={siteReg.values.every((value) => chosen.includes(value))}
                onSelectAll={() => {
                    if (upcoming) setValue('includeUpcomingSites', true, {shouldDirty: true})
                    setValue('siteKeys', available.map((site) => site.key), {shouldDirty: true, shouldValidate: true})
                }}
            >
                Sites
            </SelectAllLabel>
            <Select
                inputId="mp-sites"
                isMulti
                isSearchable={siteReg.values.length > 8}
                isClearable={false}
                closeMenuOnSelect={false}
                classNamePrefix="select"
                placeholder="Choose at least one Site"
                options={siteReg.options}
                value={siteReg.options.filter((option) => chosen.includes(option.value))}
                onChange={(options) => {
                    const picked = options.map((option) => option.value)
                    if (upcoming) setValue('includeUpcomingSites', picked.includes(UPCOMING_SITES), {shouldDirty: true})
                    setValue('siteKeys', picked.filter((value) => value !== UPCOMING_SITES), {shouldDirty: true, shouldValidate: true})
                }}
                aria-invalid={!!error}
                aria-describedby={error ? 'mp-sites-error' : 'mp-sites-help'}
            />
            {error && (
                <div id="mp-sites-error" className="error" role="alert" aria-live="polite">
                    {String(error.message)}
                </div>
            )}
            <div className="help" id="mp-sites-help">
                <ReadMore summary="The Sites this profile is offered for.">
                    <p>Remove a Site to stop offering this profile for its media.</p>
                    {upcoming && <p>With upcoming sites, a Site VODLoft sees for the first time, such as the site of a link you add later, is added to this profile's Sites.</p>}
                    <p>Media already downloaded with this profile stays where it is.</p>
                </ReadMore>
            </div>
        </div>
    )
}
