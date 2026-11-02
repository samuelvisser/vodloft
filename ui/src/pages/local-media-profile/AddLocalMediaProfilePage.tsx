import {useCallback, useEffect, useMemo, useState} from 'react'
import LocalMediaProfileForm, {LocalMediaProfileMode} from '../../components/LocalMediaProfile/LocalMediaProfileForm'
import IndexingValuesEditorButton from '../../components/LocalMediaProfile/IndexingValuesEditorButton'
import {useNavigate, useSearchParams} from 'react-router-dom'
import {useQueryClient} from '@tanstack/react-query'
import {
    LocalMediaProfileCreateIn,
    LocalMediaProfileCreateOut,
} from '../../types/schemas/local_media_profile'
import {
    MovieLocalMediaProfileCreateIn,
    MovieLocalMediaProfileCreateSchema,
} from '../../types/schemas/movie_local_media_profile'
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
import {localMediaProfileEndpoint} from '../../types/local_media_profile'


export default function AddLocalMediaProfilePage() {
    const navigate = useNavigate()
    const [searchParams] = useSearchParams()
    const qc = useQueryClient()
    const draftKey = addLocalMediaProfileDraftKey()
    const restoredDraft = useMemo(
        () => loadLocalMediaProfileDraft<LocalMediaProfileCreateIn>(draftKey),
        [draftKey],
    )
    const requestedMode = searchParams.get('type')
    const explicitMode = requestedMode === 'movie' || requestedMode === 'collection' || requestedMode === 'video'
        ? requestedMode
        : undefined
    const initialMode: LocalMediaProfileMode = explicitMode ?? restoredDraft?.mode ?? 'collection'
    const [mode, setMode] = useState<LocalMediaProfileMode>(initialMode)

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

    const formMovie = useForm<WithRoot<MovieLocalMediaProfileCreateIn>>({
        resolver: zodResolver(MovieLocalMediaProfileCreateSchema),
        mode: 'onBlur',
        shouldFocusError: true,
        defaultValues: {
            ...getZodDefaults(MovieLocalMediaProfileCreateSchema),
            ...(restoredDraft?.mode === 'movie'
                ? restoredDraft.values as Partial<MovieLocalMediaProfileCreateIn>
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

    const form = ({collection: formCollection, movie: formMovie, video: formVideo}[mode]) as UseFormReturn<any>

    useEffect(() => {
        const saveDraft = (values: Partial<LocalMediaProfileCreateIn>) => {
            saveLocalMediaProfileDraft<LocalMediaProfileCreateIn>(draftKey, {
                mode,
                values,
            })
        }

        saveDraft(form.getValues() as Partial<LocalMediaProfileCreateIn>)
        const subscription = form.watch((values) => {
            saveDraft(values as Partial<LocalMediaProfileCreateIn>)
        })
        return () => subscription.unsubscribe()
    }, [draftKey, form, mode])

    const submitFn = async (data: LocalMediaProfileCreateOut) => {
        const endpoint = localMediaProfileEndpoint(mode)
        return fetch(`${(window as any).appConfig.API_URL}/${endpoint}`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            credentials: 'include',
            body: JSON.stringify(data),
        })
    }

    const onSuccess = async () => {
        await qc.invalidateQueries({queryKey: ['localMediaProfiles']})
        clearLocalMediaProfileDraft(draftKey)
        navigate('/local-media-profiles')
    }

    const onCancel = useCallback(() => {
        clearLocalMediaProfileDraft(draftKey)
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
                <h1 id="add-media-profile-title">Add local media profile</h1>
                {mode === 'collection' && <IndexingValuesEditorButton form={form}/>}
            </div>

            <form className="form" onSubmit={onCreate} noValidate>
                <div className="form-row">
                    <label>Profile type</label>
                    <SegmentedOptions
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
                                value: 'movie',
                                label: 'Movie',
                                description: 'Store manually downloaded movies and their extras',
                            },
                            {
                                value: 'video',
                                label: 'Video',
                                description: 'Store single videos added on their own',
                            },
                        ]}
                    />
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
