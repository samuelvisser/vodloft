import {useCallback, useEffect, useMemo, useState} from 'react'
import LocalMediaProfileForm, {profileMode} from '../../components/LocalMediaProfile/LocalMediaProfileForm'
import IndexingValuesEditorButton from '../../components/LocalMediaProfile/IndexingValuesEditorButton'
import {useNavigate, useSearchParams} from 'react-router-dom'
import {useQuery, useQueryClient} from '@tanstack/react-query'
import {
    LocalMediaProfileCreateIn,
    LocalMediaProfileCreateOut,
    LocalMediaProfileRead,
} from '../../types/schemas/local_media_profile'
import {
    CollectionLocalMediaProfileCreateIn,
    CollectionLocalMediaProfileCreateSchema,
} from '../../types/schemas/collection_local_media_profile'
import {
    VideoLocalMediaProfileCreateIn,
    VideoLocalMediaProfileCreateSchema,
} from '../../types/schemas/video_local_media_profile'
import {useForm, UseFormReturn} from 'react-hook-form'
import {zodResolver} from '@hookform/resolvers/zod'
import {WithRoot} from '../../types/form'
import {buildLocalMediaProfileOnSubmit} from '../../components/LocalMediaProfile/LocalMediaProfileForm'
import SegmentedOptions from '../../components/SegmentedOptions/SegmentedOptions'
import {
    addLocalMediaProfileDraftKey,
    clearLocalMediaProfileDraft,
    loadLocalMediaProfileDraft,
    saveLocalMediaProfileDraft,
} from '../../components/LocalMediaProfile/localMediaProfileDraft'
import {getZodDefaults} from '../../utils/defaultZod'
import {LocalMediaProfileType, LocalMediaProfileTypeReg, localMediaProfileEndpoint} from '../../types/local_media_profile'
import {MUSIC_OUTPUT_TEMPLATE} from '../../components/LocalMediaProfile/outputTemplatePresets'
import {apiUrl} from '../../lib/api'


/** The settings of an existing profile as a new profile, under a name the user still has to accept. */
function duplicateValues(profile: LocalMediaProfileRead): LocalMediaProfileCreateIn {
    const values = {...profile, name: `${profile.name} (copy)`}
    if (profile.type === 'video') return VideoLocalMediaProfileCreateSchema.parse(values)
    return CollectionLocalMediaProfileCreateSchema.parse(values)
}

export default function AddLocalMediaProfilePage() {
    const [searchParams] = useSearchParams()
    const duplicateSlug = searchParams.get('duplicate')

    // The cache can still hold the profile as it was before its last save: copy it as loaded now.
    const {data: source, isFetchedAfterMount, error} = useQuery<LocalMediaProfileRead>({
        queryKey: ['localMediaProfile', duplicateSlug],
        enabled: !!duplicateSlug,
        refetchOnMount: 'always',
        queryFn: async ({signal}) => {
            const res = await fetch(`${apiUrl()}/local-media-profiles/${encodeURIComponent(duplicateSlug!)}`, {signal, credentials: 'include'})
            if (!res.ok) throw new Error(`Failed to load profile (${res.status})`)
            return await res.json() as LocalMediaProfileRead
        },
    })

    if (!duplicateSlug) return <AddLocalMediaProfileForm/>

    if (!isFetchedAfterMount || !source || error) {
        return (
            <section className="view" aria-labelledby="add-media-profile-title">
                <div className="view-header">
                    <h1 id="add-media-profile-title">Duplicate local media profile</h1>
                </div>
                <p>{!isFetchedAfterMount ? 'Loading…' : 'Profile not found.'}</p>
            </section>
        )
    }

    return <AddLocalMediaProfileForm key={source.slug} source={source}/>
}

function AddLocalMediaProfileForm({source}: { source?: LocalMediaProfileRead }) {
    const navigate = useNavigate()
    const [searchParams] = useSearchParams()
    const qc = useQueryClient()
    // A duplicate starts from its source profile and leaves the draft of a new profile alone.
    const draftKey = source ? null : addLocalMediaProfileDraftKey()
    const restoredDraft = useMemo(
        () => source
            ? {mode: source.type, values: duplicateValues(source)}
            : loadLocalMediaProfileDraft<LocalMediaProfileCreateIn>(addLocalMediaProfileDraftKey()),
        [source],
    )
    const requestedMode = searchParams.get('type')
    const explicitType = !source && LocalMediaProfileTypeReg.is(requestedMode) ? requestedMode : undefined
    const initialType: LocalMediaProfileType = explicitType || (restoredDraft?.mode ?? 'collection')
    const [profileType, setProfileType] = useState<LocalMediaProfileType>(initialType)
    const mode = profileMode(profileType)

    const formCollection = useForm<WithRoot<CollectionLocalMediaProfileCreateIn>>({
        resolver: zodResolver(CollectionLocalMediaProfileCreateSchema),
        mode: 'onBlur',
        shouldFocusError: true,
        defaultValues: {
            ...getZodDefaults(CollectionLocalMediaProfileCreateSchema),
            ...(restoredDraft?.mode === 'collection'
                ? restoredDraft.values as Partial<CollectionLocalMediaProfileCreateIn>
                : {}),
        },
    })

    // A Music profile is a Collection profile for music collections that keeps audio only.
    const formMusic = useForm<WithRoot<CollectionLocalMediaProfileCreateIn>>({
        resolver: zodResolver(CollectionLocalMediaProfileCreateSchema),
        mode: 'onBlur',
        shouldFocusError: true,
        defaultValues: {
            ...getZodDefaults(CollectionLocalMediaProfileCreateSchema),
            type: 'music',
            collectionScope: 'music',
            preferredFormat: 'format_audio_only',
            subtitleMode: 'no_subtitles',
            thumbnailMode: 'embed',
            metadataMode: 'embed',
            outputTemplate: MUSIC_OUTPUT_TEMPLATE,
            ...(restoredDraft?.mode === 'music'
                ? restoredDraft.values as Partial<CollectionLocalMediaProfileCreateIn>
                : {}),
        },
    })

    const formVideo = useForm<WithRoot<VideoLocalMediaProfileCreateIn>>({
        resolver: zodResolver(VideoLocalMediaProfileCreateSchema),
        mode: 'onBlur',
        shouldFocusError: true,
        defaultValues: {
            ...getZodDefaults(VideoLocalMediaProfileCreateSchema),
            ...(restoredDraft?.mode === 'video'
                ? restoredDraft.values as Partial<VideoLocalMediaProfileCreateIn>
                : {}),
        },
    })

    const form = ({collection: formCollection, music: formMusic, video: formVideo}[profileType]) as UseFormReturn<any>

    useEffect(() => {
        if (!draftKey) return
        const saveDraft = (values: Partial<LocalMediaProfileCreateIn>) => {
            saveLocalMediaProfileDraft<LocalMediaProfileCreateIn>(draftKey, {
                mode: profileType,
                values,
            })
        }

        saveDraft(form.getValues() as Partial<LocalMediaProfileCreateIn>)
        const subscription = form.watch((values) => {
            saveDraft(values as Partial<LocalMediaProfileCreateIn>)
        })
        return () => subscription.unsubscribe()
    }, [draftKey, form, profileType])

    const submitFn = async (data: LocalMediaProfileCreateOut) => {
        const endpoint = localMediaProfileEndpoint(profileType)
        return fetch(`${apiUrl()}/${endpoint}`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            credentials: 'include',
            body: JSON.stringify(data),
        })
    }

    const onSuccess = async () => {
        await qc.invalidateQueries({queryKey: ['localMediaProfiles']})
        if (draftKey) clearLocalMediaProfileDraft(draftKey)
        navigate('/local-media-profiles')
    }

    const onCancel = useCallback(() => {
        if (draftKey) clearLocalMediaProfileDraft(draftKey)
        navigate('/local-media-profiles')
    }, [draftKey, navigate])

    const onCreate = buildLocalMediaProfileOnSubmit(form, submitFn, {
        onSuccess,
        mode: 'create',
    })

    const {formState: {isSubmitting}} = form

    return (
        <section className="view" aria-labelledby="add-media-profile-title">
            <div className="view-header">
                <h1 id="add-media-profile-title">{source ? 'Duplicate local media profile' : 'Add local media profile'}</h1>
                {mode === 'collection' && <IndexingValuesEditorButton form={form}/>}
            </div>

            <form className="form local-media-profile-form" onSubmit={onCreate} noValidate>
                <div className="form-row">
                    <label>Profile type</label>
                    {source ? (
                        <div style={{padding: '6px 0'}}>{LocalMediaProfileTypeReg.getLabelLoose(source.type)}</div>
                    ) : <SegmentedOptions
                        name="local-media-profile-mode"
                        value={profileType}
                        onChange={(value) => setProfileType(value as LocalMediaProfileType)}
                        options={[
                            {
                                value: 'collection',
                                label: 'Collection',
                                description: 'Store downloaded collection episodes',
                            },
                            {
                                value: 'music',
                                label: 'Music',
                                description: 'Store the tracks of music collections, as audio with music tags',
                            },
                            {
                                value: 'video',
                                label: 'Video',
                                description: 'Store single videos and movies added on their own',
                            },
                        ]}
                    />}
                </div>

                <LocalMediaProfileForm form={form} mode={mode} isCreating/>

                <div className="actions">
                    <button type="button" className="btn" onClick={onCancel}>Cancel</button>
                    <input type="submit" className="btn btn-primary" value="Create profile" disabled={isSubmitting}/>
                </div>
            </form>
        </section>
    )
}
