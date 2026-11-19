import {useCallback, useEffect, useMemo, useRef} from 'react'
import {Controller, useForm, useWatch} from 'react-hook-form'
import {zodResolver} from '@hookform/resolvers/zod'
import {Link, useNavigate, useSearchParams} from 'react-router-dom'
import {useDownloadProfilesByCollectionSlug, useLocalMediaProfiles, useCollectionEpisodeTags, useCollectionSeasons, useCollections} from '../../lib/queries'
import DownloadProfileForm from '../../components/DownloadProfile/DownloadProfileForm'
import {
    DownloadProfileCreateIn, DownloadProfileCreateOut, DownloadProfileCreateSchema, defaultEpisodeFilters,
} from '../../types/schemas/download_profile'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'
import Select from '../../components/common/Select'
import {addLocalMediaProfilePath, isCollectionContext, safeReturnPath, isCollectionLocalMediaProfileAvailableFor, isLocalMediaProfileAvailableForSite, useLocalMediaProfileSelectRegistry} from "../../types/local_media_profile";
import {SelectRegistry} from "../../utils/selectRegistry";
import {buildCollectionSelectRegistry, EpisodeIdentifierReg} from "../../types/collection";
import {useQueryClient} from "@tanstack/react-query";
import {getZodDefaults} from "../../utils/defaultZod";
import ReadMore from "../../utils/ReadMore";
import {apiUrl} from '../../lib/api'
import {PreferredFormatReg} from '../../types/local_media_profile'
import RequestedField, {RequestedFieldsProvider} from '../../components/common/RequestedField'
import './AddDownloadProfilePage.css'

export default function AddDownloadProfilePage() {
    const navigate = useNavigate()
    const [searchParams] = useSearchParams()

    const {data: collections} = useCollections()
    const {data: mediaProfiles} = useLocalMediaProfiles()

    const qc = useQueryClient()

    const collectionReg: SelectRegistry = useMemo(() => buildCollectionSelectRegistry(collections), [collections])

    const form = useForm<DownloadProfileCreateIn>({
        resolver: zodResolver(DownloadProfileCreateSchema),
        mode: 'onBlur',
        shouldFocusError: true,
        defaultValues: getZodDefaults(DownloadProfileCreateSchema),
    })
    const {watch, setValue, formState: {errors, isSubmitting}} = form
    const collectionId = watch('collectionId')

    const selectedCollection = useMemo(
        () => collections?.find((collection) => collection.id === collectionId),
        [collections, collectionId],
    )
    const episodeIdentifier = selectedCollection?.episodeIdentifier
    const mediaProfileReg: SelectRegistry = useLocalMediaProfileSelectRegistry(
        mediaProfiles,
        'collection',
        isCollectionContext(selectedCollection?.type) ? selectedCollection.type : undefined,
        selectedCollection?.site?.key,
    )

    const selectCollection = useCallback((id: number) => {
        setValue('collectionId', id, {shouldDirty: true, shouldValidate: true})
        // Filters name the seasons and episode types of one collection; the new one gets its own starting filters.
        setValue('filters', [])
    }, [setValue])
    const requestedCollectionSlug = searchParams.get('collection')
    const requestedPreferredFormat = PreferredFormatReg.normalize(searchParams.get('preferredFormat'))
    // A Local Media Profile the user just created for this form, from the button under its field.
    const requestedProfileId = Number(searchParams.get('localMediaProfile')) || undefined
    const requestedEpisodeTypes = useMemo(
        () => searchParams.getAll('episodeType').filter((value) => /^[a-z][a-z-]*$/.test(value)),
        [searchParams],
    )
    const requestedDownloadEpisodeCountRaw = searchParams.get('downloadEpisodeCount')
    const parsedDownloadEpisodeCount = Number(requestedDownloadEpisodeCountRaw)
    const requestedDownloadEpisodeCount = requestedDownloadEpisodeCountRaw !== null
        && Number.isInteger(parsedDownloadEpisodeCount)
        && parsedDownloadEpisodeCount > 0
        ? parsedDownloadEpisodeCount
        : undefined

    const applyRequestedCollection = () => {
        if (!Array.isArray(collections)) return false
        const requestedCollection = collections.find((collection) => collection.slug === requestedCollectionSlug)
        if (requestedCollection) selectCollection(requestedCollection.id)
    }

    // Opened from a Stream Profile's form: back there once saved or cancelled.
    const returnTo = safeReturnPath(searchParams.get('returnTo'))
    const onCancel = useCallback(() => navigate(returnTo ?? '/download-profiles'), [navigate, returnTo])

    const submitFn = async (data: DownloadProfileCreateOut) => {
        return fetch(`${apiUrl()}/download-profiles`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            credentials: 'include',
            body: JSON.stringify(data),
        })
    }

    const onSuccess = async () => {
        await qc.invalidateQueries({queryKey: ['downloadProfilesView']})
        await qc.invalidateQueries({queryKey: ['downloadProfilesByCollectionSlug']})

        navigate(returnTo ?? '/download-profiles')
    }

    const onSubmit = buildServerAwareSubmit(form, submitFn, {
        onSuccess: onSuccess,
        successStatuses: [201],
    })

    const selectedCollectionSlug: string | undefined = selectedCollection?.slug

    // Fetch seasons and existing download profiles for the selected show
    const {data: seasonsData} = useCollectionSeasons(selectedCollectionSlug)
    const {data: collectionProfiles} = useDownloadProfilesByCollectionSlug(selectedCollectionSlug)

    // The episode tags and seasons to start with answer after the collection is picked.
    const {data: episodeTags} = useCollectionEpisodeTags({collectionId: selectedCollection?.id})
    const seasonal = episodeIdentifier === EpisodeIdentifierReg.Enum.seasonal
    const filtersDefaultedFor = useRef<number | undefined>(undefined)
    useEffect(() => {
        if (!selectedCollection || !episodeTags || (seasonal && !seasonsData)) return
        if (filtersDefaultedFor.current === selectedCollection.id) return
        filtersDefaultedFor.current = selectedCollection.id
        const latestSeason = [...(seasonsData ?? [])].sort((a, b) => b.index - a.index)[0]
        setValue('filters', defaultEpisodeFilters(episodeIdentifier, episodeTags, latestSeason?.slug))
    }, [selectedCollection, episodeTags, seasonal, seasonsData, episodeIdentifier, setValue])
    const filters = useWatch({control: form.control, name: 'filters'})
    // A link from a Stream Profile asks for the episode types and the number of episodes it streams, once the
    // collection's own starting filters are in.
    const requestedFilters = requestedEpisodeTypes.length > 0 || requestedDownloadEpisodeCount !== undefined
        ? {episodeTypes: requestedEpisodeTypes, count: requestedDownloadEpisodeCount}
        : undefined
    const applyRequestedFilters = () => {
        if (!selectedCollection || filtersDefaultedFor.current !== selectedCollection.id || !filters?.length) return false
        setValue('filters', filters.map((filter) => {
            if (filter.field === 'types' && requestedEpisodeTypes.length > 0) return {...filter, episodeTypes: requestedEpisodeTypes}
            if (filter.field === 'published' && requestedDownloadEpisodeCount !== undefined) return {...filter, count: requestedDownloadEpisodeCount}
            return filter
        }), {shouldDirty: true})
    }

    // A collection has one Download Profile per Local Media Profile.
    const usedLocalMediaProfiles = useMemo(() => new Set(
        (collectionProfiles ?? [])
            .filter((profile) => profile.collectionId === selectedCollection?.id)
            .map((profile) => profile.localMediaProfileId),
    ), [collectionProfiles, selectedCollection?.id])

    // The profiles this collection can still take that download the format a link asks for.
    const matchingProfile = selectedCollection && requestedPreferredFormat ? mediaProfiles?.find((profile) => (
        profile.preferredFormat === requestedPreferredFormat
        && isCollectionLocalMediaProfileAvailableFor(profile, selectedCollection.type)
        && isLocalMediaProfileAvailableForSite(profile, selectedCollection.site?.key)
        && !usedLocalMediaProfiles.has(profile.id)
    )) : undefined
    // None does yet: the user can add one, for this collection and the format, and come back.
    const noMatchingProfile = !!selectedCollection && !!requestedPreferredFormat && Array.isArray(mediaProfiles)
        && !!collectionProfiles && !matchingProfile
    // Where a profile created from here sends the user back to: this form, as the link opened it.
    const returnHere = useMemo(() => {
        const params = new URLSearchParams(searchParams)
        params.delete('localMediaProfile')
        return `/add-download-profile?${params}`
    }, [searchParams])
    const applyRequestedFormat = () => {
        if (!selectedCollection || !Array.isArray(mediaProfiles) || !collectionProfiles) return false
        // The list can still be the one from before the profile was created, until it loads again.
        if (requestedProfileId && !mediaProfiles.some((profile) => profile.id === requestedProfileId)) return false
        const created = mediaProfiles.find((profile) => profile.id === requestedProfileId && (
            isCollectionLocalMediaProfileAvailableFor(profile, selectedCollection.type)
            && isLocalMediaProfileAvailableForSite(profile, selectedCollection.site?.key)
            && !usedLocalMediaProfiles.has(profile.id)
        ))
        if (created) setValue('localMediaProfileId', created.id, {shouldDirty: false, shouldValidate: true})
        else if (matchingProfile) setValue('localMediaProfileId', matchingProfile.id, {shouldDirty: false, shouldValidate: true})
    }

    // A link from a Stream Profile asks for a format: the profiles that download it stand out, and another choice says so.
    const requestedFormatProfiles = useMemo(() => new Set(
        requestedPreferredFormat
            ? (mediaProfiles ?? []).filter((profile) => profile.preferredFormat === requestedPreferredFormat).map((profile) => profile.id)
            : [],
    ), [mediaProfiles, requestedPreferredFormat])
    const localMediaProfileId = watch('localMediaProfileId')
    const selectedMediaProfile = mediaProfiles?.find((profile) => profile.id === localMediaProfileId)
    const otherFormatSelected = !!requestedPreferredFormat && !!selectedMediaProfile
        && !requestedFormatProfiles.has(selectedMediaProfile.id)

    return (
        <section className="view" aria-labelledby="add-download-profile-title">
            <div className="view-header">
                <h1 id="add-download-profile-title">Add download profile</h1>
            </div>

            <RequestedFieldsProvider mode="create">
            <form className="form" onSubmit={onSubmit} noValidate>

                {errors.root && (
                    <div className="form-error-card" role="alert" aria-live="polite">
                        {String(errors.root.message)}
                    </div>
                )}

                {/* Show */}
                <div className="form-row">
                    <label htmlFor="collection-id">Collection</label>
                    <RequestedField id="collection" requested={requestedCollectionSlug} value={collectionId} apply={applyRequestedCollection}>
                    <Controller
                        control={form.control}
                        name="collectionId"
                        render={({field}) => (
                            <Select
                                inputId="collection-id"
                                classNamePrefix="select"
                                options={collectionReg.options}
                                value={collectionReg.options.find(o => Number(o.value) === field.value) ?? null}
                                onChange={(opt) => {
                                    if (opt) selectCollection(Number(opt.value))
                                    else field.onChange(undefined)
                                }}
                                onBlur={field.onBlur}
                                isDisabled={collectionReg.options.length === 0}
                                placeholder={collectionReg.options.length === 0 ? 'No collections found' : undefined}
                                isClearable
                                aria-invalid={!!errors.collectionId}
                                aria-describedby={errors.collectionId ? 'collection-errors' : undefined}
                            />
                        )}
                    />
                    </RequestedField>
                    {errors.collectionId && (
                        <div id="collection-errors" className="error" role="alert" aria-live="polite">
                            {errors.collectionId.message as string}
                        </div>
                    )}
                </div>

                {/* Local Media Profile */}
                <div className="form-row">
                    <label htmlFor="local-media-profile">Local Media Profile</label>
                    <RequestedField
                        id="localMediaProfile"
                        requested={requestedPreferredFormat ?? requestedProfileId}
                        value={localMediaProfileId}
                        apply={applyRequestedFormat}
                        fits={() => !otherFormatSelected && !noMatchingProfile}
                        incompatible={requestedPreferredFormat && (noMatchingProfile ? (
                            <span className="requested-note__with-action">
                                <span>No Local Media Profile for this collection downloads {PreferredFormatReg.getLabel(requestedPreferredFormat)} yet.</span>
                                <Link
                                    className="btn btn-small"
                                    to={addLocalMediaProfilePath({
                                        collectionType: selectedCollection?.type ?? null,
                                        siteKey: selectedCollection?.site?.key,
                                        audio: selectedCollection?.site?.audio,
                                        format: requestedPreferredFormat,
                                        returnTo: returnHere,
                                    })}
                                >
                                    Create one for {PreferredFormatReg.getLabel(requestedPreferredFormat)}
                                </Link>
                            </span>
                        ) : selectedMediaProfile && <>
                            This Local Media Profile downloads {PreferredFormatReg.getLabelLoose(selectedMediaProfile.preferredFormat)}, not the requested {PreferredFormatReg.getLabel(requestedPreferredFormat)}.
                        </>)}
                    >
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
                                isOptionDisabled={(opt) => usedLocalMediaProfiles.has(Number(opt.value))}
                                classNames={{
                                    option: ({data}) => requestedFormatProfiles.has(Number(data.value)) ? 'select__option--requested-format' : '',
                                    singleValue: ({data}) => requestedFormatProfiles.has(Number(data.value)) ? 'select__single-value--requested-format' : '',
                                }}
                                formatOptionLabel={(opt) => requestedPreferredFormat && requestedFormatProfiles.has(Number(opt.value))
                                    ? (
                                        <span className="requested-format-option">
                                            {opt.label}
                                            <span className="requested-format-option__badge">{PreferredFormatReg.getLabel(requestedPreferredFormat)}</span>
                                        </span>
                                    )
                                    : opt.label}
                                onBlur={field.onBlur}
                                isDisabled={mediaProfileReg.options.length === 0}
                                placeholder={!mediaProfiles ? 'Loading profiles...' : mediaProfileReg.options.length === 0 ? 'No profiles found' : undefined}
                                isClearable
                                aria-invalid={!!errors.localMediaProfileId}
                                aria-describedby={errors.localMediaProfileId ? 'local-media-profile-errors' : 'local-media-profile-help'}
                            />
                        )}
                    />
                    </RequestedField>
                    {errors.localMediaProfileId && (
                        <div id="local-media-profile-errors" className="error" role="alert" aria-live="polite">
                            {errors.localMediaProfileId.message as string}
                        </div>
                    )}
                    <div className="help" id="local-media-profile-help">
                        <ReadMore summary={<span>The Local Media Profile defines the type and output path of downloaded media.</span>}>
                            <p>Add a Local Media Profile to define the type of media to download and where to store it.</p>
                            <p>A collection has one Download Profile per Local Media Profile. Local Media Profiles the collection already uses cannot be chosen.</p>
                        </ReadMore>
                    </div>
                </div>

                <RequestedField id="filters" requested={requestedFilters} value={filters} apply={applyRequestedFilters}>
                    <DownloadProfileForm
                        form={form}
                        episodeIdentifier={episodeIdentifier}
                        collectionId={selectedCollection?.id}
                        seasons={seasonsData}
                        collectionRoot={false}
                        newProfile
                    />
                </RequestedField>

                <div className="actions">
                    <button type="button" className="btn" onClick={onCancel}>Cancel</button>
                    <input type="submit" className="btn btn-primary" value="Create profile" disabled={isSubmitting || !collectionId}/>
                </div>
            </form>
            </RequestedFieldsProvider>
        </section>
    )
}
