import {useCallback, useEffect, useMemo, useRef, useState} from 'react'
import {Controller, useForm} from 'react-hook-form'
import {zodResolver} from '@hookform/resolvers/zod'
import {useNavigate, useSearchParams} from 'react-router-dom'
import {useCollectionDownloadProfilesView, useCollections} from '../../lib/queries'
import {buildCollectionSelectRegistry} from '../../types/collection'
import {SelectRegistry} from '../../utils/selectRegistry'
import Select from 'react-select'
import {getZodDefaults} from '../../utils/defaultZod'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'
import StreamProfileForm from '../../components/StreamProfile/StreamProfileForm'
import SegmentedOptions from '../../components/SegmentedOptions/SegmentedOptions'
import {STREAM_PROFILE_TYPES, type StreamProfileType} from '../../components/StreamProfile/streamProfileTypes'
import {useQueryClient} from '@tanstack/react-query'
import ReadMore from "../../utils/ReadMore";
import {downloadedEpisodeTypes} from '../../components/DownloadProfile/episodeFilters'
import {apiUrl} from '../../lib/api'

// Settings whose defaults differ per type, so they start from the new type's default when the type changes.
const OWN_FIELDS = {streamLiveEpisodes: true}

export default function AddStreamProfilePage() {
    const navigate = useNavigate()
    const [searchParams] = useSearchParams()
    const qc = useQueryClient()

    const [mode, setMode] = useState<StreamProfileType>('rss')
    const createSchema = STREAM_PROFILE_TYPES[mode].createSchema

    const {data: collections} = useCollections()
    const collectionReg: SelectRegistry = buildCollectionSelectRegistry(collections)

    const form = useForm<any>({
        resolver: (values, context, options) => zodResolver(createSchema as any)(values, context, options),
        mode: 'onBlur',
        shouldFocusError: true,
        defaultValues: getZodDefaults(STREAM_PROFILE_TYPES.rss.createSchema),
    })

    // Another type keeps what both types have, and starts its own settings from their defaults.
    const changeMode = (next: StreamProfileType) => {
        if (next === mode) return
        const current = form.getValues()
        const schema = STREAM_PROFILE_TYPES[next].createSchema
        const shared = Object.keys(schema.shape).filter((key) => key in current && !(key in OWN_FIELDS))
        form.reset({...getZodDefaults(schema), ...Object.fromEntries(shared.map((key) => [key, current[key]]))})
        setMode(next)
    }
    const {watch, formState: {errors, isSubmitting}} = form
    const prefillApplied = useRef(false)
    const requestedCollectionSlug = searchParams.get('collection')
    const selectedCollectionId = watch('collectionId')
    const useDownloads = watch('useDownloads')
    const selectedCollection = collections?.find((collection) => collection.id === selectedCollectionId)
    const {data: downloadProfiles} = useCollectionDownloadProfilesView(selectedCollection?.slug)

    const downloadProfileDefaults = useMemo(() => {
        if (!selectedCollection) return []
        if (!downloadProfiles) return undefined
        return downloadProfiles
            .map((profile) => ({
                id: profile.id,
                preferredFormat: profile.localMediaProfilePreferredFormat,
                episodeTypes: downloadedEpisodeTypes(profile.filters),
                enabled: profile.enableProfile,
            }))
    }, [downloadProfiles, selectedCollection?.slug])

    useEffect(() => {
        if (prefillApplied.current || !requestedCollectionSlug || !Array.isArray(collections)) return
        const requestedCollection = collections.find((collection) => collection.slug === requestedCollectionSlug)
        if (!requestedCollection) return

        form.setValue('collectionId', requestedCollection.id, {shouldDirty: false, shouldValidate: true})
        prefillApplied.current = true
    }, [form, requestedCollectionSlug, collections])

    const onCancel = useCallback(() => navigate('/stream-profiles'), [navigate])

    const submitFn = async (data: unknown) => {
        return fetch(`${apiUrl()}/${STREAM_PROFILE_TYPES[mode].endpoint}`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            credentials: 'include',
            body: JSON.stringify(data),
        })
    }

    const onSuccess = async (result: {id: number}) => {
        await qc.invalidateQueries({queryKey: ['streamProfilesView']})
        navigate(`/edit-stream-profile/${mode}/${result.id}`)
    }

    const onSubmit = buildServerAwareSubmit(form as any, submitFn, {
        onSuccess,
        successStatuses: [201],
    })
    const waitingForDownloadProfileDefaults = !!selectedCollectionId && useDownloads && downloadProfiles === undefined

    return (
        <section className="view" aria-labelledby="add-stream-profile-title">
            <div className="view-header">
                <h1 id="add-stream-profile-title">Add Stream Profile</h1>
            </div>

            <form className="form" onSubmit={onSubmit} noValidate>
                {errors.root && (
                    <div className="form-error-card" role="alert" aria-live="polite">
                        {String(errors.root.message)}
                    </div>
                )}

                <div className="form-row">
                    <label htmlFor="collection-id">Collection</label>
                    <Controller
                        control={form.control}
                        name={"collectionId"}
                        render={({field}) => (
                            <Select
                                inputId="collection-id"
                                classNamePrefix="select"
                                options={collectionReg.options}
                                value={collectionReg.options.find(o => Number(o.value) === field.value) ?? null}
                                onChange={(opt) => field.onChange((opt as any) ? Number((opt as any).value) : undefined)}
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
                            {String(errors.collectionId.message)}
                        </div>
                    )}
                </div>

                <div className="form-row">
                    <label>Profile type</label>
                    <SegmentedOptions
                        name="stream-profile-mode"
                        value={mode}
                        onChange={(v) => changeMode(v as StreamProfileType)}
                        options={[
                            {
                                value: 'rss',
                                label: 'RSS',
                                description: (
                                    <ReadMore summary={<span>Open RSS feed for the collection.</span>}>
                                        <p>RSS is the technology used to distribute podcast feeds.</p>
                                        <p>With an RSS Stream Profile in VODLoft, you can effectively create your very own podcast from
                                        the collections in your library. This is great when you want to listen to the versions included with
                                        your membership using your favorite podcast app.</p>
                                    </ReadMore>
                                ),
                            },
                            {
                                value: 'iptv',
                                label: 'IPTV',
                                description: (
                                    <ReadMore summary={<span>A TV channel with a programme guide.</span>}>
                                        <p>
                                            With an IPTV Stream Profile, the collection becomes a channel in TV apps such as
                                            TiviMate, Kodi&apos;s IPTV Simple, or Jellyfin and Emby Live TV. Live episodes play
                                            live on the channel, and the guide shows the episodes of the last week.
                                        </p>
                                    </ReadMore>
                                ),
                            },
                        ]}
                    />
                </div>

                <StreamProfileForm
                    form={form as any}
                    mode={mode}
                    collectionRoot={false}
                    isCreating
                    downloadProfileDefaults={downloadProfileDefaults}
                    collectionSlug={selectedCollection?.slug}
                    collectionTitle={selectedCollection?.title}
                />

                <div className="actions">
                    <button type="button" className="btn" onClick={onCancel}>Cancel</button>
                    <input
                        type="submit"
                        className="btn btn-primary"
                        value="Create profile"
                        disabled={isSubmitting || !selectedCollectionId || waitingForDownloadProfileDefaults}
                    />
                </div>
            </form>
        </section>
    )
}
