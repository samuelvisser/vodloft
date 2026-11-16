import {useCallback, useEffect, useMemo, useRef, useState} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {useForm} from 'react-hook-form'
import {zodResolver} from '@hookform/resolvers/zod'
import {Link, useNavigate, useParams} from 'react-router-dom'
import {useQuery, useQueryClient} from '@tanstack/react-query'
import {useCollectionDownloadProfilesView} from '../../lib/queries'
import {StreamProfileReadView} from '../../types/schemas/stream_profile_base'
import StreamProfileForm from '../../components/StreamProfile/StreamProfileForm'
import ConfirmDialog from '../../components/ConfirmDialog/ConfirmDialog'
import ConfirmDeleteDialog, {ConfirmDeleteDialogRef} from '../../components/ConfirmDeleteDialog/ConfirmDeleteDialog'
import {isStreamProfileType, STREAM_PROFILE_TYPES} from '../../components/StreamProfile/streamProfileTypes'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'
import {faIcon} from '../../icons/faIcon'
import {downloadedEpisodeTypes} from '../../components/DownloadProfile/episodeFilters'
import {apiUrl} from '../../lib/api'


type RouteParams = { type?: string; id?: string }

export default function EditStreamProfilePage() {
    const navigate = useNavigate()
    const {type, id} = useParams<RouteParams>()
    const qc = useQueryClient()

    const profileId = id ? Number(id) : undefined

    // The cache can still hold the profile as it was before the last save, so the form waits for this visit's own
    // load instead of starting from it.
    const {data: streamProfile, isFetchedAfterMount, error} = useQuery<StreamProfileReadView | undefined>({
        queryKey: ['streamProfile', id],
        enabled: !!id,
        refetchOnMount: 'always',
        queryFn: async ({signal}) => {
            const res = await fetch(`${apiUrl()}/stream-profiles/as-view/${profileId}`, { signal, credentials: 'include' })
            if (!res.ok) throw new Error(`Failed to load profile (${res.status})`)
            return await res.json() as Promise<StreamProfileReadView>
        },
    })

    const {data: downloadProfiles} = useCollectionDownloadProfilesView(streamProfile?.collectionSlug)
    const downloadProfileDefaults = useMemo(() => {
        if (!streamProfile) return []
        if (!downloadProfiles) return undefined
        return downloadProfiles
            .map((profile) => ({
                id: profile.id,
                preferredFormat: profile.localMediaProfilePreferredFormat,
                episodeTypes: downloadedEpisodeTypes(profile.filters),
                enabled: profile.enableProfile,
            }))
    }, [downloadProfiles, streamProfile?.collectionSlug])

    const profileType = isStreamProfileType(type) ? STREAM_PROFILE_TYPES[type] : undefined
    const updateSchema = (profileType ?? STREAM_PROFILE_TYPES.rss).updateSchema
    const form = useForm<any>({
        resolver: (values, context, options) => zodResolver(updateSchema as any)(values, context, options),
        mode: 'onBlur',
        shouldFocusError: true,
    })
    const {formState: {errors, isSubmitting}} = form

    // A later background refetch must not undo the user's edits, so the form is filled once.
    const initializedId = useRef<string | undefined>(undefined)
    useEffect(() => {
        if (!isFetchedAfterMount || !streamProfile || initializedId.current === id) return
        initializedId.current = id
        form.reset(updateSchema.parse({
            ...streamProfile.streamProfileImpl,
            title: streamProfile.streamProfileImpl.effectiveTitle,
        }))
    }, [isFetchedAfterMount, streamProfile, id, form, updateSchema])

    const onCancel = useCallback(() => navigate('/stream-profiles'), [navigate])
    const confirmRef = useRef<ConfirmDeleteDialogRef>(null)

    const [regenerating, setRegenerating] = useState(false)
    const [regenerateConfirmOpen, setRegenerateConfirmOpen] = useState(false)
    const onRegenerateToken = useCallback(() => setRegenerateConfirmOpen(true), [])
    const regenerateToken = useCallback(async () => {
        if (!profileId || regenerating) return
        setRegenerateConfirmOpen(false)
        setRegenerating(true)
        try {
            const res = await fetch(`${apiUrl()}/${profileType?.endpoint}/${profileId}/regenerate-token`, {
                method: 'POST',
                credentials: 'include',
            })
            if (res.ok) {
                const updated = await res.json()
                if (type === 'rss') form.setValue('feedUrl', updated.feedUrl, {shouldDirty: false})
                await qc.invalidateQueries({queryKey: ['streamProfile', id]})
                await qc.invalidateQueries({queryKey: ['streamProfilesView']})
            }
        } finally {
            setRegenerating(false)
        }
    }, [profileId, regenerating, id, qc, form, profileType, type])

    const submitFn = async (data: unknown) => {
        if (!profileId || !profileType) return undefined as any
        return fetch(`${apiUrl()}/${profileType.endpoint}/${profileId}`, {
            method: 'PATCH',
            headers: {'Content-Type': 'application/json'},
            credentials: 'include',
            body: JSON.stringify(data),
        })
    }

    const onSuccess = async () => {
        await qc.invalidateQueries({queryKey: ['streamProfilesView']})
        void qc.invalidateQueries({queryKey: ['streamProfile', id], refetchType: 'none'})
        navigate('/stream-profiles')
    }

    const onSubmit = buildServerAwareSubmit(form as any, async (dataOut: unknown) => {
        const res = await submitFn(dataOut)
        if (res?.ok) await onSuccess()
        return res
    })

    if (!profileType || !profileId || (streamProfile && streamProfile.type !== type)) {
        return (
            <section className="view" aria-labelledby="edit-stream-profile-title">
                <div className="view-header">
                    <h1 id="edit-stream-profile-title">Edit stream profile</h1>
                </div>
                <p>Profile not found.</p>
                <div className="actions" style={{marginTop: 12}}>
                    <Link className="btn" to="/stream-profiles">Back</Link>
                </div>
            </section>
        )
    }

    return (
        <section className="view" aria-labelledby="edit-stream-profile-title">
            <div className="view-header">
                <h1 id="edit-stream-profile-title">Edit stream profile</h1>
            </div>

            {!isFetchedAfterMount ? (
                <p>Loading…</p>
            ) : error ? (
                <p>{error.message}</p>
            ) : (
                <form className="form" onSubmit={onSubmit} noValidate>
                    <div className="form-row">
                        <label>Profile type</label>
                        <div style={{padding: '6px 0'}}>{profileType.label}</div>
                    </div>

                    <div className="form-row">
                        <label>Collection</label>
                        <div style={{padding: '6px 0'}}>
                            <Link className="quiet-link" to={`/collection/${streamProfile?.collectionSlug}`}>{streamProfile?.collectionTitle}</Link>
                        </div>
                    </div>

                    {errors.root && (
                        <div className="form-error-card" role="alert" aria-live="polite">
                            {String(errors.root.message)}
                        </div>
                    )}

                    <StreamProfileForm
                        form={form as any}
                        mode={type as 'rss' | 'iptv'}
                        collectionRoot={false}
                        playlistPath={streamProfile?.streamProfileImpl.type === 'iptv' ? streamProfile.streamProfileImpl.playlistPath : undefined}
                        guidePath={streamProfile?.streamProfileImpl.type === 'iptv' ? streamProfile.streamProfileImpl.guidePath : undefined}
                        onRegenerateToken={onRegenerateToken}
                        regeneratingToken={regenerating}
                        downloadProfileDefaults={downloadProfileDefaults}
                        collectionSlug={streamProfile?.collectionSlug}
                        collectionTitle={streamProfile?.collectionTitle}
                    />

                    <div className="actions">
                        <button
                            type="button"
                            className="btn btn-danger"
                            style={{marginRight: 'auto'}}
                            onClick={() => confirmRef.current?.open(streamProfile)}
                        >
                            <FontAwesomeIcon icon={faIcon('fass', 'trash')} aria-hidden="true"/>
                            <span>Delete profile</span>
                        </button>
                        <button type="button" className="btn" onClick={onCancel}>Cancel</button>
                        <input type="submit" className="btn btn-primary" value="Save changes" disabled={isSubmitting} />
                    </div>
                </form>
            )}

            <ConfirmDeleteDialog
                ref={confirmRef}
                title="Delete stream profile"
                subjectProp="collectionTitle"
                deleteRequest={() => fetch(`${apiUrl()}/${profileType?.endpoint}/${profileId}`, {method: 'DELETE', credentials: 'include'})}
                invalidateQueries={[['streamProfilesView']]}
                inUseMessage="This stream profile is in use, it cannot be deleted"
                onDeleted={onCancel}
            />

            <ConfirmDialog
                open={regenerateConfirmOpen}
                title={type === 'rss' ? 'Regenerate RSS feed URL' : 'Regenerate channel addresses'}
                onDismiss={() => setRegenerateConfirmOpen(false)}
                icon={faIcon('fass', 'rotate')}
                iconTone="danger"
                confirmButton={{
                    label: type === 'rss' ? 'Regenerate URL' : 'Regenerate addresses',
                    onClick: regenerateToken,
                    icon: faIcon('fass', 'rotate'),
                    className: 'btn btn-danger',
                }}
            >
                {type === 'rss' ? (
                    <>
                        <p>Regenerating will immediately invalidate the current feed URL.</p>
                        <p>Any podcast app already subscribed to it will need the new URL.</p>
                    </>
                ) : (
                    <>
                        <p>Regenerating will immediately invalidate the channel&apos;s current playlist, guide and channel addresses.</p>
                        <p>Any TV app that uses the channel&apos;s own playlist will need the new one. Your account&apos;s playlist with all your channels keeps working.</p>
                    </>
                )}
            </ConfirmDialog>
        </section>
    )
}
