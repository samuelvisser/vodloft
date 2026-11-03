import {useCallback, useEffect, useMemo} from 'react'
import {Controller, useForm} from 'react-hook-form'
import {zodResolver} from '@hookform/resolvers/zod'
import {Link, useNavigate, useParams} from 'react-router-dom'
import {useDownloadProfilesByCollectionSlug, useLocalMediaProfiles, useCollectionSeasons} from '../../lib/queries'
import DownloadProfileForm from '../../components/DownloadProfile/DownloadProfileForm'
import {
    DownloadProfileUpdateIn, DownloadProfileUpdateOut, DownloadProfileUpdateSchema, forEpisodeIdentifier,
} from '../../types/schemas/download_profile'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'
import Select from 'react-select'
import {isLocalMediaProfileAvailableForSource, useLocalMediaProfileSelectRegistry} from "../../types/local_media_profile";
import {DownloadProfileReadView} from "../../types/schemas/download_profile_view";
import {useQuery, useQueryClient} from "@tanstack/react-query";
import ReadMore from "../../utils/ReadMore";
import {EpisodeIdentifierReg} from "../../types/collection";

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
            const res = await fetch(`${(window as any).appConfig.API_URL}/download-profiles/as-view/${profileId}`, {signal, credentials: 'include'})
            if (!res.ok) throw new Error(`Failed to load profile (${res.status})`)
            return await res.json() as Promise<DownloadProfileReadView>
        },
    })
    const collectionTitle: string | undefined = downloadProfile?.collectionTitle

    const {data: mediaProfiles} = useLocalMediaProfiles()
    const {data: seasonsData} = useCollectionSeasons(downloadProfile?.collectionSlug)
    const {data: collectionProfiles} = useDownloadProfilesByCollectionSlug(downloadProfile?.collectionSlug)

    const episodeIdentifier = downloadProfile?.collectionEpisodeIdentifier
    const schema = useMemo(
        () => forEpisodeIdentifier(DownloadProfileUpdateSchema, episodeIdentifier),
        [episodeIdentifier],
    )
    const form = useForm<DownloadProfileUpdateIn>({
        resolver: zodResolver(schema),
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
    // The profile already in use stays offered after it was limited to other Sources.
    const offeredProfiles = useMemo(
        () => mediaProfiles?.filter((profile) => (
            profile.id === downloadProfile?.localMediaProfileId
            || isLocalMediaProfileAvailableForSource(profile, downloadProfile?.collectionSourceKey)
        )),
        [mediaProfiles, downloadProfile?.localMediaProfileId, downloadProfile?.collectionSourceKey],
    )
    const mediaProfileReg = useLocalMediaProfileSelectRegistry(
        offeredProfiles,
        'collection',
        collectionType === 'podcast' || collectionType === 'series' ? collectionType : undefined,
    )
    const selectedLocalMediaProfileId = form.watch('localMediaProfileId')

    const disabledEpisodeTypes = useMemo(() => {
        if (typeof selectedLocalMediaProfileId !== 'number') return new Set<string>()
        return new Set<string>(
            (collectionProfiles ?? [])
                .filter((profile) => (
                    profile.id !== profileId
                    && profile.localMediaProfileId === selectedLocalMediaProfileId
                ))
                .flatMap((profile) => profile.epIdTypeList)
        )
    }, [profileId, selectedLocalMediaProfileId, collectionProfiles])

    const onCancel = useCallback(() => navigate('/download-profiles'), [navigate])

    const submitFn = async (data: DownloadProfileUpdateOut) => {
        return fetch(`${(window as any).appConfig.API_URL}/download-profiles/${profileId}`, {
            method: 'PATCH',
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

    const onSubmit = buildServerAwareSubmit(form, async (dataOut: DownloadProfileUpdateOut) => {
        const res = await submitFn(dataOut)
        if (res?.ok) await onSuccess()
        return res
    })

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
                <form className="form" onSubmit={onSubmit} noValidate>
                    {errors.root && (
                        <div className="form-error-card" role="alert" aria-live="polite">
                            {String(errors.root.message)}
                        </div>
                    )}

                    <div className="form-row">
                        <label>Collection</label>
                        <div style={{padding: '6px 0'}}>
                            <Link to={`/collection/${downloadProfile?.collectionSlug}`}>{collectionTitle}</Link>
                        </div>
                    </div>

                    <div className="form-row">
                        <label>Episode identification</label>
                        <div style={{padding: '6px 0'}}>{EpisodeIdentifierReg.getLabelLoose(episodeIdentifier ?? '')}</div>
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
                                <p>The same Local Media Profile can be used by multiple Download Profiles for a collection, but each episode type can belong to only one of those profiles.</p>
                            </ReadMore>
                        </div>
                    </div>

                    <DownloadProfileForm
                        form={form}
                        episodeIdentifier={episodeIdentifier}
                        collectionId={downloadProfile?.collectionId}
                        seasons={seasonsData}
                        collectionRoot={false}
                        disabledEpisodeTypes={disabledEpisodeTypes}
                    />

                    <div className="actions">
                        <button type="button" className="btn" onClick={onCancel}>Cancel</button>
                        <input type="submit" className="btn btn-primary" value="Save changes" disabled={isSubmitting}/>
                    </div>
                </form>
            )}
        </section>
    )
}
