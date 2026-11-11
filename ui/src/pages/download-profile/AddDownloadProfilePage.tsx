import {useCallback, useEffect, useMemo, useRef} from 'react'
import {Controller, useForm} from 'react-hook-form'
import {zodResolver} from '@hookform/resolvers/zod'
import {useNavigate, useSearchParams} from 'react-router-dom'
import {useDownloadProfilesByCollectionSlug, useLocalMediaProfiles, useCollectionEpisodeTags, useCollectionSeasons, useCollections} from '../../lib/queries'
import DownloadProfileForm from '../../components/DownloadProfile/DownloadProfileForm'
import {
    DownloadProfileCreateIn, DownloadProfileCreateOut, DownloadProfileCreateSchema, defaultEpisodeFilters,
} from '../../types/schemas/download_profile'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'
import Select from 'react-select'
import {isCollectionLocalMediaProfileAvailableFor, isLocalMediaProfileAvailableForSite, useLocalMediaProfileSelectRegistry} from "../../types/local_media_profile";
import {SelectRegistry} from "../../utils/selectRegistry";
import {buildCollectionSelectRegistry, EpisodeIdentifierReg} from "../../types/collection";
import {useQueryClient} from "@tanstack/react-query";
import {getZodDefaults} from "../../utils/defaultZod";
import ReadMore from "../../utils/ReadMore";
import {apiUrl} from '../../lib/api'

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
        selectedCollection?.type === 'podcast' || selectedCollection?.type === 'series' ? selectedCollection.type : undefined,
        selectedCollection?.site?.key,
    )

    const selectCollection = useCallback((id: number) => {
        setValue('collectionId', id, {shouldDirty: true, shouldValidate: true})
        // Filters name the seasons and episode types of one collection; the new one gets its own starting filters.
        setValue('filters', [])
    }, [setValue])
    const prefillApplied = useRef(false)
    const mediaProfilePrefillApplied = useRef(false)
    const requestedCollectionSlug = searchParams.get('collection')
    const requestedPreferredFormat = searchParams.get('preferredFormat')
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

    useEffect(() => {
        if (prefillApplied.current || !requestedCollectionSlug || !Array.isArray(collections)) return
        const requestedCollection = collections.find((collection) => collection.slug === requestedCollectionSlug)
        if (!requestedCollection) return

        selectCollection(requestedCollection.id)
        prefillApplied.current = true
    }, [requestedCollectionSlug, selectCollection, collections])

    const onCancel = useCallback(() => navigate('/download-profiles'), [navigate])

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

        navigate('/download-profiles')
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
        // A link from a Stream Profile asks for the episode types and the number of episodes it streams.
        const filters = defaultEpisodeFilters(episodeIdentifier, episodeTags, latestSeason?.slug).map((filter) => {
            if (filter.field === 'types' && requestedEpisodeTypes.length > 0) return {...filter, episodeTypes: requestedEpisodeTypes}
            if (filter.field === 'published' && requestedDownloadEpisodeCount !== undefined) return {...filter, count: requestedDownloadEpisodeCount}
            return filter
        })
        setValue('filters', filters)
    }, [selectedCollection, episodeTags, seasonal, seasonsData, episodeIdentifier, requestedEpisodeTypes, requestedDownloadEpisodeCount, setValue])

    // A collection has one Download Profile per Local Media Profile.
    const usedLocalMediaProfiles = useMemo(() => new Set(
        (collectionProfiles ?? [])
            .filter((profile) => profile.collectionId === selectedCollection?.id)
            .map((profile) => profile.localMediaProfileId),
    ), [collectionProfiles, selectedCollection?.id])

    useEffect(() => {
        if (
            mediaProfilePrefillApplied.current
            || !requestedPreferredFormat
            || !selectedCollection
            || !Array.isArray(mediaProfiles)
        ) return

        const matchingProfile = mediaProfiles.find((profile) => (
            profile.type === 'collection'
            && profile.preferredFormat === requestedPreferredFormat
            && isCollectionLocalMediaProfileAvailableFor(profile, selectedCollection.type)
            && isLocalMediaProfileAvailableForSite(profile, selectedCollection.site?.key)
            && !usedLocalMediaProfiles.has(profile.id)
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
        selectedCollection,
        usedLocalMediaProfiles,
    ])

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
                    <label htmlFor="collection-id">Collection</label>
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
                    {errors.collectionId && (
                        <div id="collection-errors" className="error" role="alert" aria-live="polite">
                            {errors.collectionId.message as string}
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
                                isOptionDisabled={(opt) => usedLocalMediaProfiles.has(Number(opt.value))}
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
                            <p>A collection has one Download Profile per Local Media Profile. Local Media Profiles the collection already uses cannot be chosen.</p>
                        </ReadMore>
                    </div>
                </div>

                <DownloadProfileForm
                    form={form}
                    episodeIdentifier={episodeIdentifier}
                    collectionId={selectedCollection?.id}
                    seasons={seasonsData}
                    collectionRoot={false}
                    newProfile
                />

                <div className="actions">
                    <button type="button" className="btn" onClick={onCancel}>Cancel</button>
                    <input type="submit" className="btn btn-primary" value="Create profile" disabled={isSubmitting || !collectionId}/>
                </div>
            </form>
        </section>
    )
}
