import {useCallback, useEffect, useMemo, useRef, useState} from 'react'
import {Controller, useForm} from 'react-hook-form'
import {zodResolver} from '@hookform/resolvers/zod'
import {useNavigate, useSearchParams} from 'react-router-dom'
import {useCollectionDownloadProfilesView, useCollections} from '../../lib/queries'
import {buildCollectionSelectRegistry} from '../../types/collection'
import {SelectRegistry} from '../../utils/selectRegistry'
import Select from '../../components/common/ReactSelect'
import {getZodDefaults} from '../../utils/defaultZod'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'
import StreamProfileForm from '../../components/StreamProfile/StreamProfileForm'
import SegmentedOptions from '../../components/SegmentedOptions/SegmentedOptions'
import {STREAM_PROFILE_TYPES, type StreamProfileType} from '../../components/StreamProfile/streamProfileTypes'
import {useQueryClient} from '@tanstack/react-query'
import ReadMore from "../../utils/ReadMore";
import {downloadedEpisodeTypes} from '../../components/DownloadProfile/episodeFilters'
import {apiUrl} from '../../lib/api'
import UnsavedChangesBar from '../../components/FormDraft/UnsavedChangesBar'
import {
    addStreamProfileDraftKey,
    clearStreamProfileDraft,
    loadStreamProfileDraft,
    saveStreamProfileDraft,
} from '../../components/StreamProfile/streamProfileDraft'

// Settings whose defaults differ per type, so they start from the new type's default when the type changes.
const OWN_FIELDS = {useDownloads: true, useSourceStream: true, streamLiveEpisodes: true}

export default function AddStreamProfilePage() {
    // Discarding a restored draft mounts a fresh form, so every field starts from its default again.
    const [generation, setGeneration] = useState(0)
    return (
        <AddStreamProfileForm
            key={generation}
            onDiscardDraft={() => {
                clearStreamProfileDraft(addStreamProfileDraftKey())
                setGeneration((current) => current + 1)
            }}
        />
    )
}

function AddStreamProfileForm({onDiscardDraft}: {onDiscardDraft: () => void}) {
    const navigate = useNavigate()
    const [searchParams] = useSearchParams()
    const qc = useQueryClient()
    // What was typed here before, such as before leaving to create the Download Profile this profile needs.
    const draftKey = addStreamProfileDraftKey()
    const restoredDraft = useMemo(() => loadStreamProfileDraft(draftKey), [draftKey])

    const [mode, setMode] = useState<StreamProfileType>(restoredDraft?.mode ?? 'rss')
    const createSchema = STREAM_PROFILE_TYPES[mode].createSchema

    const {data: collections} = useCollections()
    const collectionReg: SelectRegistry = buildCollectionSelectRegistry(collections)

    const form = useForm<any>({
        resolver: (values, context, options) => zodResolver(createSchema as any)(values, context, options),
        mode: 'onBlur',
        shouldFocusError: true,
        defaultValues: {...getZodDefaults(STREAM_PROFILE_TYPES[mode].createSchema), ...restoredDraft?.values},
    })

    useEffect(() => {
        const subscription = form.watch((values) => saveStreamProfileDraft(draftKey, {mode, values}))
        return () => subscription.unsubscribe()
    }, [draftKey, form, mode])

    // Another type keeps what both types have, and starts its own settings from their defaults.
    const changeMode = (next: StreamProfileType) => {
        if (next === mode) return
        const current = form.getValues()
        const schema = STREAM_PROFILE_TYPES[next].createSchema
        const shared = Object.keys(schema.shape).filter((key) => key in current && !(key in OWN_FIELDS))
        form.reset({...getZodDefaults(schema), ...Object.fromEntries(shared.map((key) => [key, current[key]]))})
        setMode(next)
        saveStreamProfileDraft(draftKey, {mode: next, values: form.getValues()})
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
        // A restored draft already has the collection the user chose.
        if (restoredDraft?.values.collectionId != null) {
            prefillApplied.current = true
            return
        }
        const requestedCollection = collections.find((collection) => collection.slug === requestedCollectionSlug)
        if (!requestedCollection) return

        form.setValue('collectionId', requestedCollection.id, {shouldDirty: false, shouldValidate: true})
        prefillApplied.current = true
    }, [form, requestedCollectionSlug, collections])

    const onCancel = useCallback(() => {
        clearStreamProfileDraft(draftKey)
        navigate('/stream-profiles')
    }, [draftKey, navigate])

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
        clearStreamProfileDraft(draftKey)
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

            <form id="add-stream-profile-form" className="form" onSubmit={onSubmit} noValidate>
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
                                            live on the channel, and TV apps with catch-up play older episodes from the guide.
                                        </p>
                                    </ReadMore>
                                ),
                            },
                            {
                                value: 'webdav',
                                label: 'WebDAV',
                                description: (
                                    <ReadMore summary={<span>A network folder laid out as a TV show.</span>}>
                                        <p>
                                            With a WebDAV Stream Profile, the collection becomes a read-only network folder that
                                            media players such as Infuse, Kodi and VLC show as a TV show, with its artwork and
                                            episode details. It lists the episodes VODLoft has a whole file of.
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

            {restoredDraft ? (
                <UnsavedChangesBar
                    title="Unsaved changes restored"
                    message="This form was restored from a profile you started in this browser. It has not been created in VODLoft yet."
                >
                    <button className="btn" type="button" disabled={isSubmitting} onClick={onDiscardDraft}>
                        Discard
                    </button>
                    <button className="btn btn-primary" type="submit" form="add-stream-profile-form" disabled={isSubmitting}>
                        {isSubmitting ? 'Creating…' : 'Create profile'}
                    </button>
                </UnsavedChangesBar>
            ) : null}
        </section>
    )
}
