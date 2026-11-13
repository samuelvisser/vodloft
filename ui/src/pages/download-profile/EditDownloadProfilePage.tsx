import {type FormEvent, useCallback, useEffect, useMemo, useRef, useState} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {Controller, useForm} from 'react-hook-form'
import {zodResolver} from '@hookform/resolvers/zod'
import {Link, useNavigate, useParams} from 'react-router-dom'
import {useDownloadProfileOutOfScope, useDownloadProfilesByCollectionSlug, useLocalMediaProfiles, useCollectionSeasons} from '../../lib/queries'
import DownloadProfileForm from '../../components/DownloadProfile/DownloadProfileForm'
import {
    DownloadProfileUpdateIn, DownloadProfileUpdateOut, DownloadProfileUpdateSchema,
} from '../../types/schemas/download_profile'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'
import Select from 'react-select'
import {isLocalMediaProfileAvailableForSite, useLocalMediaProfileSelectRegistry} from "../../types/local_media_profile";
import {DownloadProfileReadView} from "../../types/schemas/download_profile_view";
import {useQuery, useQueryClient} from "@tanstack/react-query";
import ReadMore from "../../utils/ReadMore";
import {apiUrl} from '../../lib/api'
import {faIcon} from '../../icons/faIcon'
import ConfirmDeleteDialog, {ConfirmDeleteDialogRef} from '../../components/ConfirmDeleteDialog/ConfirmDeleteDialog'
import ConfirmDialog from '../../components/ConfirmDialog/ConfirmDialog'
import {downloadsSummary, mayDeleteOutOfScope, useDeleteOutOfScope} from '../../components/DownloadProfile/OutOfScopeDownloadsDialog'
import {OutOfScopeDownloadsSchema, type OutOfScopeDownload} from '../../types/schemas/download_profile'

type RouteParams = { id?: string }

export default function EditDownloadProfilePage() {
    const navigate = useNavigate()
    const {id} = useParams<RouteParams>()
    const qc = useQueryClient()

    const profileId = id ? Number(id) : undefined

    // Fetch the latest profile by id
    const {data: downloadProfile, isLoading, error} = useQuery<DownloadProfileReadView | undefined>({
        queryKey: ['downloadProfile', id],
        enabled: !!id,
        refetchOnMount: 'always',
        queryFn: async ({signal}) => {
            const res = await fetch(`${apiUrl()}/download-profiles/as-view/${profileId}`, {signal, credentials: 'include'})
            if (!res.ok) throw new Error(`Failed to load profile (${res.status})`)
            return await res.json() as Promise<DownloadProfileReadView>
        },
    })
    const collectionTitle: string | undefined = downloadProfile?.collectionTitle

    const {data: mediaProfiles} = useLocalMediaProfiles()
    const {data: seasonsData} = useCollectionSeasons(downloadProfile?.collectionSlug)
    const {data: collectionProfiles} = useDownloadProfilesByCollectionSlug(downloadProfile?.collectionSlug)

    const episodeIdentifier = downloadProfile?.collectionEpisodeIdentifier
    const form = useForm<DownloadProfileUpdateIn>({
        resolver: zodResolver(DownloadProfileUpdateSchema),
        mode: 'onBlur',
        shouldFocusError: true,
    })
    const {formState: {errors}} = form

    // Populate form with existing data once it’s loaded
    useEffect(() => {
        if (!downloadProfile) return
        form.reset(DownloadProfileUpdateSchema.parse(downloadProfile))
    }, [downloadProfile, form])

    const collectionType = downloadProfile?.collectionType
    // The profile already in use stays offered after it was limited to other Sites.
    const offeredProfiles = useMemo(
        () => mediaProfiles?.filter((profile) => (
            profile.id === downloadProfile?.localMediaProfileId
            || isLocalMediaProfileAvailableForSite(profile, downloadProfile?.collectionSiteKey)
        )),
        [mediaProfiles, downloadProfile?.localMediaProfileId, downloadProfile?.collectionSiteKey],
    )
    const mediaProfileReg = useLocalMediaProfileSelectRegistry(
        offeredProfiles,
        'collection',
        collectionType === 'podcast' || collectionType === 'series' ? collectionType : undefined,
    )
    // A collection has one Download Profile per Local Media Profile.
    const usedLocalMediaProfiles = useMemo(() => new Set(
        (collectionProfiles ?? [])
            .filter((profile) => profile.id !== profileId)
            .map((profile) => profile.localMediaProfileId),
    ), [collectionProfiles, profileId])

    const onCancel = useCallback(() => navigate('/download-profiles'), [navigate])
    const confirmRef = useRef<ConfirmDeleteDialogRef>(null)

    // Narrowing the filters never deletes by itself: saving asks whether to delete the downloads that fall out.
    const mayDeleteFiles = mayDeleteOutOfScope()
    const {data: outOfScopeBefore} = useDownloadProfileOutOfScope(profileId, mayDeleteFiles)
    const [fallingOut, setFallingOut] = useState<{remove: OutOfScopeDownload[], kept: OutOfScopeDownload[]} | null>(null)
    const deleteDecisionRef = useRef<OutOfScopeDownload[] | null>(null)
    const deleteOutOfScope = useDeleteOutOfScope(
        profileId ?? 0, `${collectionTitle ?? ''} (${downloadProfile?.localMediaProfileName ?? ''})`,
    )

    const submitFn = async (data: DownloadProfileUpdateOut) => {
        return fetch(`${apiUrl()}/download-profiles/${profileId}`, {
            method: 'PATCH',
            headers: {'Content-Type': 'application/json'},
            credentials: 'include',
            body: JSON.stringify(data),
        })
    }

    const onSuccess = async () => {
        const toDelete = deleteDecisionRef.current
        deleteDecisionRef.current = null
        await qc.invalidateQueries({queryKey: ['downloadProfilesView']})
        await qc.invalidateQueries({queryKey: ['downloadProfilesByCollectionSlug']})
        void qc.invalidateQueries({queryKey: ['downloadProfileView', profileId]})
        void qc.invalidateQueries({queryKey: ['downloadProfileStatistics', profileId]})
        void qc.invalidateQueries({queryKey: ['downloadProfileOutOfScope', profileId]})

        if (toDelete?.length) {
            // The delete runs in the background; the profile's page shows its progress.
            navigate(`/download-profile/${profileId}`)
            await deleteOutOfScope(toDelete.map((download) => download.id))
            return
        }
        navigate('/download-profiles')
    }

    const onSubmit = buildServerAwareSubmit(form, async (dataOut: DownloadProfileUpdateOut) => {
        const res = await submitFn(dataOut)
        if (res?.ok) await onSuccess()
        else deleteDecisionRef.current = null
        return res
    })

    /** The profile's downloads that the form's filters leave out once saved, which its saved filters keep. */
    const newlyOutOfScope = async (data: DownloadProfileUpdateOut) => {
        const response = await fetch(`${apiUrl()}/download-profiles/${profileId}/out-of-scope-downloads/preview`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            credentials: 'include',
            body: JSON.stringify({downloadWithCountdown: data.downloadWithCountdown, filters: data.filters}),
        })
        if (!response.ok) return []
        const before = new Set((outOfScopeBefore ?? []).map((download) => download.id))
        return OutOfScopeDownloadsSchema.parse(await response.json()).filter((download) => !before.has(download.id))
    }

    const onFormSubmit = (event: FormEvent<HTMLFormElement>) => {
        if (!mayDeleteFiles || outOfScopeBefore === undefined) {
            void onSubmit(event)
            return
        }
        void form.handleSubmit(async (data) => {
            const falling = await newlyOutOfScope(data as DownloadProfileUpdateOut)
            const remove = falling.filter((download) => download.keptBy === null)
            if (!remove.length) {
                void onSubmit()
                return
            }
            setFallingOut({remove, kept: falling.filter((download) => download.keptBy !== null)})
        })(event)
    }

    const continueSave = (remove: OutOfScopeDownload[] | null) => {
        deleteDecisionRef.current = remove
        setFallingOut(null)
        void onSubmit()
    }

    const {formState: {isSubmitting}} = form

    if (!profileId) {
        return (
            <section className="view" aria-labelledby="edit-download-profile-title">
                <div className="view-header">
                    <h1 id="edit-download-profile-title">Edit Download Profile</h1>
                </div>
                <p>Profile not found.</p>
                <div className="actions" style={{marginTop: 12}}>
                    <Link className="btn" to="/download-profiles">Back</Link>
                </div>
            </section>
        )
    }

    return (
        <section className="view" aria-labelledby="edit-download-profile-title">
            <div className="view-header">
                <h1 id="edit-download-profile-title">Edit Download Profile</h1>
            </div>

            {isLoading ? (
                <p>Loading…</p>
            ) : error ? (
                <p>{error.message}</p>
            ) : (
                <form className="form" onSubmit={onFormSubmit} noValidate>
                    {errors.root && (
                        <div className="form-error-card" role="alert" aria-live="polite">
                            {String(errors.root.message)}
                        </div>
                    )}

                    <div className="form-row">
                        <label>Collection</label>
                        <div style={{padding: '6px 0'}}>
                            <Link className="quiet-link" to={`/collection/${downloadProfile?.collectionSlug}`}>{collectionTitle}</Link>
                        </div>
                    </div>

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
                                    onChange={(opt) => field.onChange((opt as any) ? Number((opt as any).value) : null)}
                                    isOptionDisabled={(opt) => usedLocalMediaProfiles.has(Number(opt.value))}
                                    onBlur={field.onBlur}
                                    isDisabled={mediaProfileReg.options.length === 0}
                                    placeholder={!mediaProfiles ? 'Loading profiles...' : mediaProfileReg.options.length === 0 ? 'No profiles found' : undefined}
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
                                <p>When changing the Local Media Profile for an existing Download Profile, new episodes will be downloaded to the new
                                    location in the new format. Old episodes will be left in their original location.</p>
                                <p>A collection has one Download Profile per Local Media Profile. Local Media Profiles the collection already uses cannot be chosen.</p>
                            </ReadMore>
                        </div>
                    </div>

                    <DownloadProfileForm
                        form={form}
                        episodeIdentifier={episodeIdentifier}
                        collectionId={downloadProfile?.collectionId}
                        seasons={seasonsData}
                        collectionRoot={false}
                    />

                    <div className="actions">
                        <button
                            type="button"
                            className="btn btn-danger"
                            style={{marginRight: 'auto'}}
                            onClick={() => confirmRef.current?.open(downloadProfile)}
                        >
                            <FontAwesomeIcon icon={faIcon('fass', 'trash')} aria-hidden="true"/>
                            <span>Delete profile</span>
                        </button>
                        <button type="button" className="btn" onClick={onCancel}>Cancel</button>
                        <input type="submit" className="btn btn-primary" value="Save changes" disabled={isSubmitting}/>
                    </div>
                </form>
            )}

            <ConfirmDialog
                open={fallingOut !== null}
                title="Delete downloads now outside this profile?"
                icon={faIcon('fass', 'trash')}
                iconTone="danger"
                onDismiss={() => {
                    if (!isSubmitting) setFallingOut(null)
                }}
                dismissOnOverlayClick={!isSubmitting}
                cancelButton={{
                    label: 'Save and keep them',
                    disabled: isSubmitting,
                    onClick: () => continueSave(null),
                }}
                confirmButton={{
                    label: isSubmitting ? 'Saving…' : 'Save and delete',
                    className: 'btn btn-danger',
                    disabled: isSubmitting,
                    onClick: () => continueSave(fallingOut?.remove ?? null),
                }}
            >
                <p className="modal-text">
                    These changes leave out {fallingOut ? downloadsSummary(fallingOut.remove) : ''} that this
                    Download Profile downloaded or adopted. Delete them and their files? That runs in the background,
                    and the profile's page shows how far it is.
                </p>
                <p className="modal-text">
                    Episodes you downloaded by hand are never deleted, and neither are downloads marked to keep
                    {fallingOut?.kept.length ? ` (${downloadsSummary(fallingOut.kept)} here)` : ''}.
                </p>
                <p className="modal-text">
                    Close this dialog to keep editing. You can also delete them later from the Actions menu on the profile's page.
                </p>
            </ConfirmDialog>

            <ConfirmDeleteDialog
                ref={confirmRef}
                title="Delete download profile"
                subjectProp="collectionTitle"
                deleteRequest={() => fetch(`${apiUrl()}/download-profiles/${profileId}`, {method: 'DELETE', credentials: 'include'})}
                invalidateQueries={[['downloadProfilesView'], ['downloadProfilesByCollectionSlug']]}
                inUseMessage="This download profile is in use, it cannot be deleted"
                deletedMessage={(p) => `Deleted the Download Profile of ${p.collectionTitle}`}
                onDeleted={onCancel}
            />
        </section>
    )
}
