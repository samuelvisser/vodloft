import {collectionWords} from '../../lib/collectionWords'
import {type FormEvent, useCallback, useEffect, useMemo, useRef, useState} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {Controller, useForm, useWatch} from 'react-hook-form'
import {zodResolver} from '@hookform/resolvers/zod'
import {Link, useNavigate, useParams, useSearchParams} from 'react-router-dom'
import {
    downloadProfileOutOfScopePreviewQuery, useDownloadProfileOutOfScopePreview, useDownloadProfilesByCollectionSlug,
    useCollections, useEpisodeTagsInCollection, useLocalMediaProfiles, useCollectionSeasons, type OutOfScopePreviewBody,
} from '../../lib/queries'
import DownloadProfileForm from '../../components/DownloadProfile/DownloadProfileForm'
import {
    DownloadProfileUpdateIn, DownloadProfileUpdateOut, DownloadProfileUpdateSchema,
} from '../../types/schemas/download_profile'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'
import Select from '../../components/common/Select'
import {safeReturnPath, useLocalMediaProfileSelectRegistry} from "../../types/local_media_profile";
import LocalMediaProfileFitNote, {useLocalMediaProfilesForCollection} from '../../components/DownloadProfile/LocalMediaProfileFitNote'
import RequestedField, {RequestedFieldsProvider} from '../../components/common/RequestedField'
import {DownloadProfileReadView} from "../../types/schemas/download_profile_view";
import {useQuery, useQueryClient} from "@tanstack/react-query";
import ReadMore from "../../utils/ReadMore";
import {apiUrl} from '../../lib/api'
import {faIcon} from '../../icons/faIcon'
import ConfirmDeleteDialog, {ConfirmDeleteDialogRef} from '../../components/ConfirmDeleteDialog/ConfirmDeleteDialog'
import ConfirmDialog from '../../components/ConfirmDialog/ConfirmDialog'
import {
    downloadsSummary, leftOutByText, mayDeleteOutOfScope, OutOfScopeChecklist, useDeleteOutOfScope, useOutOfScopePicks,
} from '../../components/DownloadProfile/OutOfScopeDownloadsDialog'
import type {OutOfScopePreview} from '../../types/schemas/download_profile'
import Breadcrumb from '../../components/common/Breadcrumb/Breadcrumb'

type RouteParams = { id?: string }

export default function EditDownloadProfilePage() {
    const navigate = useNavigate()
    const {id} = useParams<RouteParams>()
    const qc = useQueryClient()

    const profileId = id ? Number(id) : undefined

    // Fetch the latest profile by id. The cache can still hold the profile as it was before the last save, so the
    // form waits for this visit's own load instead of starting from it.
    const {data: downloadProfile, isFetchedAfterMount, error} = useQuery<DownloadProfileReadView | undefined>({
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

    // Populate the form once this visit's load is in; a later background refetch must not undo the user's edits.
    const initializedId = useRef<string | undefined>(undefined)
    useEffect(() => {
        if (!isFetchedAfterMount || !downloadProfile || initializedId.current === id) return
        initializedId.current = id
        form.reset(DownloadProfileUpdateSchema.parse(downloadProfile))
    }, [isFetchedAfterMount, downloadProfile, id, form])

    const {data: collections} = useCollections()
    const collection = collections?.find((candidate) => candidate.slug === downloadProfile?.collectionSlug)
    // Only the profiles available for the collection are offered, and the one this Download Profile already uses,
    // which says so under the field when it no longer fits.
    const offeredProfiles = useLocalMediaProfilesForCollection(mediaProfiles, collection, downloadProfile?.localMediaProfileId)
    const mediaProfileReg = useLocalMediaProfileSelectRegistry(offeredProfiles, 'collection')
    // A collection has one Download Profile per Local Media Profile.
    const usedLocalMediaProfiles = useMemo(() => new Set(
        (collectionProfiles ?? [])
            .filter((profile) => profile.id !== profileId)
            .map((profile) => profile.localMediaProfileId),
    ), [collectionProfiles, profileId])

    // Opened from a Stream Profile's form: back there once saved or cancelled.
    const [searchParams] = useSearchParams()
    const returnTo = safeReturnPath(searchParams.get('returnTo'))
    // A Local Media Profile the user just created for this form, from the button under its field.
    const requestedProfileId = Number(searchParams.get('localMediaProfile')) || undefined
    const returnHere = useMemo(() => {
        const params = new URLSearchParams(searchParams)
        params.delete('localMediaProfile')
        const query = params.toString()
        return `/edit-download-profile/${id}${query ? `?${query}` : ''}`
    }, [searchParams, id])
    const localMediaProfileId = useWatch({control: form.control, name: 'localMediaProfileId'})
    const applyRequestedProfile = () => {
        // The list can still be the one from before the profile was created, until it loads again.
        if (!offeredProfiles?.some((profile) => profile.id === requestedProfileId)) return false
        form.setValue('localMediaProfileId', requestedProfileId!, {shouldDirty: true, shouldValidate: true})
    }
    const onCancel = useCallback(() => navigate(returnTo ?? '/download-profiles'), [navigate, returnTo])
    const confirmRef = useRef<ConfirmDeleteDialogRef>(null)

    // Narrowing the filters never deletes by itself: saving asks whether to delete the downloads that fall out.
    const mayDeleteFiles = mayDeleteOutOfScope()
    const {data: tags} = useEpisodeTagsInCollection(downloadProfile?.collectionSlug)
    /** The form's Which episodes lines being saved, while the dialog asks what to delete. */
    const [fallingOut, setFallingOut] = useState<{body: OutOfScopePreviewBody, deleteOlder: boolean} | null>(null)
    const preview = useDownloadProfileOutOfScopePreview(profileId, fallingOut?.body ?? null)
    const previewSummary = preview.data?.pages[0]
    const picks = useOutOfScopePicks(previewSummary, fallingOut)
    const deleteDecisionRef = useRef<number[] | null>(null)
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
        void qc.invalidateQueries({queryKey: ['downloadProfile', id], refetchType: 'none'})
        void qc.invalidateQueries({queryKey: ['downloadProfileStatistics', profileId]})
        void qc.invalidateQueries({queryKey: ['downloadProfileOutOfScope', profileId]})
        qc.removeQueries({queryKey: ['downloadProfileOutOfScopePreview', profileId]})

        if (toDelete?.length) {
            // The delete runs in the background; the profile's page shows its progress.
            navigate(`/download-profile/${profileId}`)
            await deleteOutOfScope({notKept: false, kept: false, include: toDelete})
            return
        }
        navigate(returnTo ?? '/download-profiles')
    }

    const onSubmit = buildServerAwareSubmit(form, async (dataOut: DownloadProfileUpdateOut) => {
        const res = await submitFn(dataOut)
        if (res?.ok) await onSuccess()
        else deleteDecisionRef.current = null
        return res
    })

    const onFormSubmit = (event: FormEvent<HTMLFormElement>) => {
        if (!mayDeleteFiles) {
            void onSubmit(event)
            return
        }
        void form.handleSubmit(async (data) => {
            const out = data as DownloadProfileUpdateOut
            const body = {downloadWithCountdown: out.downloadWithCountdown, filters: out.filters}
            let falling: OutOfScopePreview | undefined
            try {
                // Read here first, so the dialog only opens when saving leaves out a download nothing keeps.
                falling = (await qc.fetchInfiniteQuery(downloadProfileOutOfScopePreviewQuery(profileId, body))).pages[0]
            } catch {
                falling = undefined
            }
            if (!falling?.notKeptIds.length) {
                void onSubmit()
                return
            }
            setFallingOut({body, deleteOlder: out.deleteOlderEpisodes})
        })(event)
    }

    /** The downloads picked in the dialog, also the ones that did not load: the saved profile can no longer tell them apart. */
    const pickedIds = () => {
        if (!previewSummary) return []
        const {notKept, kept, include = [], exclude = []} = picks.choice
        const start = [...(notKept ? previewSummary.notKeptIds : []), ...(kept ? previewSummary.keptIds : [])]
        const left = new Set(exclude)
        return [...start.filter((id) => !left.has(id)), ...include]
    }

    const continueSave = (remove: number[] | null) => {
        deleteDecisionRef.current = remove
        setFallingOut(null)
        void onSubmit()
    }

    const typeLabel = (key: string) => tags?.find((tag) => tag.key === key)?.label ?? key
    const seasonLabel = (slug: string) => seasonsData?.find((season) => season.slug === slug)?.name ?? slug
    const previewFilterText = (index: number) => leftOutByText(
        fallingOut?.body.filters[index] as Parameters<typeof leftOutByText>[0], typeLabel, seasonLabel, fallingOut?.deleteOlder ?? false, collectionWords(downloadProfile?.collectionType).season,
    )

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
            {downloadProfile && (
                <Breadcrumb className="page-breadcrumb" items={[
                    {label: 'Download Profiles', to: '/download-profiles'},
                    {label: 'Profile', to: `/download-profile/${downloadProfile.id}`},
                ]}/>
            )}
            <div className="view-header">
                <h1 id="edit-download-profile-title">Edit Download Profile</h1>
            </div>

            {!isFetchedAfterMount ? (
                <p>Loading…</p>
            ) : error ? (
                <p>{error.message}</p>
            ) : (
                <RequestedFieldsProvider mode="edit" ready={!!downloadProfile && initializedId.current === id}>
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
                        <RequestedField
                            id="localMediaProfile"
                            requested={requestedProfileId}
                            value={localMediaProfileId}
                            apply={applyRequestedProfile}
                            changed="The Local Media Profile you just created was chosen here. Save to use it."
                        >
                        <Controller
                            control={form.control}
                            name="localMediaProfileId"
                            render={({field}) => (
                                <Select
                                    inputId="local-media-profile"
                                    options={mediaProfileReg.options}
                                    value={mediaProfileReg.options.find(o => Number(o.value) === field.value) ?? null}
                                    onChange={(opt) => field.onChange((opt as any) ? Number((opt as any).value) : null)}
                                    isOptionDisabled={(opt) => usedLocalMediaProfiles.has(Number(opt.value))}
                                    onBlur={field.onBlur}
                                    isDisabled={mediaProfileReg.options.length === 0}
                                    placeholder={!offeredProfiles ? 'Loading profiles...' : mediaProfileReg.options.length === 0 ? 'No profiles found' : undefined}
                                    aria-invalid={!!errors.localMediaProfileId}
                                    aria-describedby={errors.localMediaProfileId ? 'local-media-profile-errors' : 'local-media-profile-help'}
                                />
                            )}
                        />
                        </RequestedField>
                        <LocalMediaProfileFitNote
                            profiles={mediaProfiles}
                            selectedId={localMediaProfileId}
                            used={usedLocalMediaProfiles}
                            collection={collection}
                            returnTo={returnHere}
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
                        collectionType={downloadProfile?.collectionType}
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
                </RequestedFieldsProvider>
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
                    label: isSubmitting ? 'Saving…' : picks.count ? `Save and delete ${picks.count.toLocaleString()}` : 'Save and delete',
                    className: 'btn btn-danger',
                    disabled: isSubmitting || !picks.count,
                    onClick: () => continueSave(pickedIds()),
                }}
                className="out-of-scope-dialog"
            >
                <p className="modal-text">
                    These changes leave out downloads that this Download Profile downloaded or adopted. Delete the ones
                    you pick, and their files? That runs in the background once the profile is saved, and the profile's
                    page shows how far it is.
                </p>
                <p className="modal-text">
                    Episodes you downloaded by hand are never listed or deleted. Downloads marked to keep are listed,
                    but disabled by default.
                </p>
                <OutOfScopeChecklist
                    query={preview}
                    picks={picks}
                    filterText={previewFilterText}
                    typeLabel={typeLabel}
                    empty="Saving leaves out none of its downloads."
                />
                <p className="modal-text">
                    {picks.count
                        ? <>Saving deletes {downloadsSummary(picks.count, picks.sizeBytes)} and their files. This can't be undone.</>
                        : 'Nothing is picked, so saving deletes nothing.'}
                    {' '}Close this dialog to keep editing. You can also delete them later from the Actions menu on the profile's page.
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
