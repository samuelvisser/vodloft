import {useCallback, useEffect, useMemo, useRef} from 'react'
import {Controller, useForm} from 'react-hook-form'
import {zodResolver} from '@hookform/resolvers/zod'
import {useNavigate, useSearchParams} from 'react-router-dom'
import {useDownloadProfilesByShowSlug, useLocalMediaProfiles, useShowEpisodeTags, useShowSeasons, useShows} from '../../lib/queries'
import DownloadProfileForm from '../../components/DownloadProfile/DownloadProfileForm'
import {
    DownloadProfileCreateIn, DownloadProfileCreateOut, DownloadProfileCreateSchema,
    downloadProfileDefaultsFor, forEpisodeIdentifier,
} from '../../types/schemas/download_profile'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'
import Select from 'react-select'
import {isShowLocalMediaProfileAvailableFor, useLocalMediaProfileSelectRegistry} from "../../types/local_media_profile";
import {SelectRegistry} from "../../utils/selectRegistry";
import {buildShowSelectRegistry} from "../../types/show";
import {useQueryClient} from "@tanstack/react-query";
import {getZodDefaults} from "../../utils/defaultZod";
import ReadMore from "../../utils/ReadMore";
import {SeasonItem} from "../../components/DownloadProfile/DownloadProfileSeasonFilter";
import {SeasonRead} from "../../types/schemas/season";

export default function AddDownloadProfilePage() {
    const navigate = useNavigate()
    const [searchParams] = useSearchParams()

    const {data: shows} = useShows()
    const {data: mediaProfiles} = useLocalMediaProfiles()

    const qc = useQueryClient()

    const showReg: SelectRegistry = useMemo(() => buildShowSelectRegistry(shows), [shows])

    const form = useForm<DownloadProfileCreateIn>({
        // Which filters apply follows the chosen show, so the schema does too.
        resolver: (values, context, options) => zodResolver(forEpisodeIdentifier(
            DownloadProfileCreateSchema,
            shows?.find((show) => show.id === values.showId)?.episodeIdentifier,
        ))(values, context, options),
        mode: 'onBlur',
        shouldFocusError: true,
        defaultValues: getZodDefaults(DownloadProfileCreateSchema),
    })
    const {watch, setValue, getFieldState, formState: {errors, isSubmitting}} = form
    const showId = watch('showId')
    const localMediaProfileId = watch('localMediaProfileId')

    const selectedShow = useMemo(
        () => shows?.find((show) => show.id === showId),
        [shows, showId],
    )
    const episodeIdentifier = selectedShow?.episodeIdentifier
    const mediaProfileReg: SelectRegistry = useLocalMediaProfileSelectRegistry(
        mediaProfiles,
        'show',
        selectedShow?.type === 'podcast' || selectedShow?.type === 'series' ? selectedShow.type : undefined,
    )

    const selectShow = useCallback((id: number) => {
        setValue('showId', id, {shouldDirty: true, shouldValidate: true})
        // Seasons belong to one show; the other filters start from what fits the show.
        setValue('seasons', [], {shouldDirty: true})
        const defaults = downloadProfileDefaultsFor(shows?.find((show) => show.id === id)?.episodeIdentifier, undefined)
        if (!getFieldState('downloadDaysInPast').isDirty && !getFieldState('downloadEpisodeCount').isDirty) {
            setValue('downloadDaysInPast', defaults.downloadDaysInPast)
        }
    }, [getFieldState, setValue, shows])
    // The episode tags to start with depend on the show's Source, which answers after the show is picked.
    const {data: episodeTags} = useShowEpisodeTags({showId: selectedShow?.id})
    useEffect(() => {
        if (!episodeTags || getFieldState('epIdTypeList').isDirty) return
        setValue('epIdTypeList', downloadProfileDefaultsFor(episodeIdentifier, episodeTags).epIdTypeList)
    }, [episodeIdentifier, episodeTags, getFieldState, setValue])
    const prefillApplied = useRef(false)
    const limitPrefillApplied = useRef(false)
    const mediaProfilePrefillApplied = useRef(false)
    const episodeTypesPrefillApplied = useRef(false)
    const requestedShowSlug = searchParams.get('show')
    const requestedPreferredFormat = searchParams.get('preferredFormat')
    const requestedEpisodeTypeValues = searchParams.getAll('episodeType')
    const requestedEpisodeTypes = requestedEpisodeTypeValues.filter((value) => /^[a-z][a-z-]*$/.test(value))
    const requestedDownloadEpisodeCountRaw = searchParams.get('downloadEpisodeCount')
    const parsedDownloadEpisodeCount = Number(requestedDownloadEpisodeCountRaw)
    const requestedDownloadEpisodeCount = requestedDownloadEpisodeCountRaw !== null
        && Number.isInteger(parsedDownloadEpisodeCount)
        && parsedDownloadEpisodeCount > 0
        ? parsedDownloadEpisodeCount
        : undefined

    useEffect(() => {
        if (prefillApplied.current || !requestedShowSlug || !Array.isArray(shows)) return
        const requestedShow = shows.find((show) => show.slug === requestedShowSlug)
        if (!requestedShow) return

        selectShow(requestedShow.id)
        prefillApplied.current = true
    }, [requestedShowSlug, selectShow, shows])

    useEffect(() => {
        if (limitPrefillApplied.current || requestedDownloadEpisodeCount === undefined) return

        setValue('downloadDaysInPast', 0, {shouldDirty: true, shouldValidate: true})
        setValue('downloadEpisodeCount', requestedDownloadEpisodeCount, {
            shouldDirty: true,
            shouldValidate: true,
        })
        limitPrefillApplied.current = true
    }, [setValue, requestedDownloadEpisodeCount])

    useEffect(() => {
        if (episodeTypesPrefillApplied.current || requestedEpisodeTypes.length === 0) return

        setValue('epIdTypeList', [...requestedEpisodeTypes], {
            shouldDirty: true,
            shouldValidate: true,
        })
        episodeTypesPrefillApplied.current = true
    }, [setValue, requestedEpisodeTypes])

    const onCancel = useCallback(() => navigate('/download-profiles'), [navigate])

    const submitFn = async (data: DownloadProfileCreateOut) => {
        return fetch(`${(window as any).appConfig.API_URL}/download-profiles`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            credentials: 'include',
            body: JSON.stringify(data),
        })
    }

    const onSuccess = async () => {
        await qc.invalidateQueries({queryKey: ['downloadProfilesView']})
        await qc.invalidateQueries({queryKey: ['downloadProfilesByShowSlug']})

        navigate('/download-profiles')
    }

    const onSubmit = buildServerAwareSubmit(form, submitFn, {
        onSuccess: onSuccess,
        successStatuses: [201],
    })

    useEffect(() => {
        if (
            mediaProfilePrefillApplied.current
            || !requestedPreferredFormat
            || !selectedShow
            || !Array.isArray(mediaProfiles)
        ) return

        const matchingProfile = mediaProfiles.find((profile) => (
            profile.type === 'show'
            && profile.preferredFormat === requestedPreferredFormat
            && isShowLocalMediaProfileAvailableFor(profile, selectedShow.type)
        ))
        if (!matchingProfile) return

        setValue('localMediaProfileId', matchingProfile.id, {
            shouldDirty: false,
            shouldValidate: true,
        })
        mediaProfilePrefillApplied.current = true
    }, [
        setValue,
        mediaProfiles,
        requestedPreferredFormat,
        selectedShow,
    ])
    const selectedShowSlug: string | undefined = selectedShow?.slug

    // Fetch seasons and existing download profiles for the selected show
    const {data: seasonsData} = useShowSeasons(selectedShowSlug)
    const {data: showProfiles} = useDownloadProfilesByShowSlug(selectedShowSlug)

    // Prepare seasons for the season filter (detached: name, slug)
    const seasonsForForm: SeasonItem[] = useMemo((): SeasonItem[] => (seasonsData ?? []).map((s: SeasonRead): SeasonItem => ({
        name: s.name,
        slug: s.slug,
    })), [seasonsData])

    const disabledEpisodeTypes = useMemo(() => {
        if (typeof localMediaProfileId !== 'number' || !selectedShow) return new Set<string>()
        return new Set<string>(
            (showProfiles ?? [])
                .filter((profile) => (
                    profile.showId === selectedShow.id
                    && profile.localMediaProfileId === localMediaProfileId
                ))
                .flatMap((profile) => profile.epIdTypeList)
        )
    }, [localMediaProfileId, selectedShow?.id, showProfiles])

    return (
        <section className="view" aria-labelledby="add-download-profile-title">
            <div className="view-header">
                <h1 id="add-download-profile-title">Add download profile</h1>
            </div>

            <form className="form" onSubmit={onSubmit} noValidate>

                {errors.root && (
                    <div className="form-error-card" role="alert" aria-live="polite">
                        {String(errors.root.message)}
                    </div>
                )}

                {/* Show */}
                <div className="form-row">
                    <label htmlFor="show-id">Show</label>
                    <Controller
                        control={form.control}
                        name="showId"
                        render={({field}) => (
                            <Select
                                inputId="show-id"
                                classNamePrefix="select"
                                options={showReg.options}
                                value={showReg.options.find(o => Number(o.value) === field.value) ?? null}
                                onChange={(opt) => {
                                    if (opt) selectShow(Number(opt.value))
                                    else field.onChange(undefined)
                                }}
                                onBlur={field.onBlur}
                                isDisabled={showReg.options.length === 0}
                                placeholder={showReg.options.length === 0 ? 'No shows found' : undefined}
                                isClearable
                                aria-invalid={!!errors.showId}
                                aria-describedby={errors.showId ? 'show-errors' : undefined}
                            />
                        )}
                    />
                    {errors.showId && (
                        <div id="show-errors" className="error" role="alert" aria-live="polite">
                            {errors.showId.message as string}
                        </div>
                    )}
                </div>

                {/* Local Media Profile */}
                <div className="form-row">
                    <label htmlFor="local-media-profile">Local Media Profile</label>
                    <Controller
                        control={form.control}
                        name="localMediaProfileId"
                        render={({field}) => (
                            <Select
                                inputId="local-media-profile"
                                classNamePrefix="select"
                                options={mediaProfileReg.options}
                                value={mediaProfileReg.options.find(o => Number(o.value) === field.value) ?? null}
                                onChange={(opt) => field.onChange(opt ? Number(opt.value) : null)}
                                onBlur={field.onBlur}
                                isDisabled={mediaProfileReg.options.length === 0}
                                placeholder={!mediaProfiles ? 'Loading profiles...' : mediaProfileReg.options.length === 0 ? 'No profiles found' : undefined}
                                isClearable
                                aria-invalid={!!errors.localMediaProfileId}
                                aria-describedby={errors.localMediaProfileId ? 'local-media-profile-errors' : 'local-media-profile-help'}
                            />
                        )}
                    />
                    {errors.localMediaProfileId && (
                        <div id="local-media-profile-errors" className="error" role="alert" aria-live="polite">
                            {errors.localMediaProfileId.message as string}
                        </div>
                    )}
                    <div className="help" id="local-media-profile-help">
                        <ReadMore summary={<span>The Local Media Profile defines the type and output path of downloaded media.</span>}>
                            <p>Add a Local Media Profile to define the type of media to download and where to store it.</p>
                            <p>The same Local Media Profile can be used by multiple Download Profiles for a show, but each episode type can belong to only one of those profiles.</p>
                        </ReadMore>
                    </div>
                </div>

                <DownloadProfileForm
                    form={form}
                    episodeIdentifier={episodeIdentifier}
                    showId={selectedShow?.id}
                    seasons={seasonsForForm}
                    showRoot={false}
                    disabledEpisodeTypes={disabledEpisodeTypes}
                />

                <div className="actions">
                    <button type="button" className="btn" onClick={onCancel}>Cancel</button>
                    <input type="submit" className="btn btn-primary" value="Create profile" disabled={isSubmitting || !showId}/>
                </div>
            </form>
        </section>
    )
}
