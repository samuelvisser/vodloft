import {useCallback, useEffect, useMemo, useState} from 'react'
import LocalMediaProfileForm, {LocalMediaProfileMode} from '../../components/LocalMediaProfile/LocalMediaProfileForm'
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
import UnsavedChangesBar from '../../components/FormDraft/UnsavedChangesBar'
import {getZodDefaults} from '../../utils/defaultZod'
import {LocalMediaProfileTypeReg, localMediaProfileEndpoint} from '../../types/local_media_profile'
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
    // Discarding a restored draft mounts a fresh form, so every field starts from its default again.
    const [generation, setGeneration] = useState(0)

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

    if (!duplicateSlug) {
        return (
            <AddLocalMediaProfileForm
                key={generation}
                onDiscardDraft={() => {
                    clearLocalMediaProfileDraft(addLocalMediaProfileDraftKey())
                    setGeneration((current) => current + 1)
                }}
            />
        )
    }

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

function AddLocalMediaProfileForm({source, onDiscardDraft}: { source?: LocalMediaProfileRead, onDiscardDraft?: () => void }) {
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
    const explicitMode = !source && (requestedMode === 'collection' || requestedMode === 'video')
        ? requestedMode
        : undefined
    const initialMode: LocalMediaProfileMode = explicitMode || (restoredDraft?.mode ?? 'collection')
    const [mode, setMode] = useState<LocalMediaProfileMode>(initialMode)
    // A draft is only kept once something is typed, so a draft that is there holds the user's own changes.
    const showRestored = !source && !!restoredDraft

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

    const form = ({collection: formCollection, video: formVideo}[mode]) as UseFormReturn<any>


    useEffect(() => {
        if (!draftKey) return
        const saveDraft = (values: Partial<LocalMediaProfileCreateIn>) => {
            saveLocalMediaProfileDraft<LocalMediaProfileCreateIn>(draftKey, {
                mode,
                values,
            })
        }

        const subscription = form.watch((values) => {
            saveDraft(values as Partial<LocalMediaProfileCreateIn>)
        })
        return () => subscription.unsubscribe()
    }, [draftKey, form, mode])

    const submitFn = async (data: LocalMediaProfileCreateOut) => {
        const endpoint = localMediaProfileEndpoint(mode)
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
    const formId = 'add-local-media-profile-form'

    return (
        <section className="view" aria-labelledby="add-media-profile-title">
            <div className="view-header">
                <h1 id="add-media-profile-title">{source ? 'Duplicate local media profile' : 'Add local media profile'}</h1>
                {mode === 'collection' && <IndexingValuesEditorButton form={form}/>}
            </div>

            <form id={formId} className="form local-media-profile-form" onSubmit={onCreate} noValidate>
                <div className="form-row">
                    <label>Profile type</label>
                    {source ? (
                        <div style={{padding: '6px 0'}}>{LocalMediaProfileTypeReg.getLabelLoose(source.type)}</div>
                    ) : <SegmentedOptions
                        name="local-media-profile-mode"
                        value={mode}
                        onChange={(value) => setMode(value as LocalMediaProfileMode)}
                        options={[
                            {
                                value: 'collection',
                                label: 'Collection',
                                description: 'Store downloaded collection episodes',
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

            {showRestored ? (
                <UnsavedChangesBar
                    title="Unsaved changes restored"
                    message="This form was restored from a profile you started in this browser. It has not been created in VODLoft yet."
                >
                    <button className="btn" type="button" disabled={isSubmitting} onClick={onDiscardDraft}>
                        Discard
                    </button>
                    <button className="btn btn-primary" type="submit" form={formId} disabled={isSubmitting}>
                        {isSubmitting ? 'Creating…' : 'Create profile'}
                    </button>
                </UnsavedChangesBar>
            ) : null}
        </section>
    )
}
