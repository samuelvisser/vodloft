import {useCallback, useEffect, useMemo, useRef, useState} from 'react'
import {zodResolver} from '@hookform/resolvers/zod'
import {useForm} from 'react-hook-form'
import {useQueryClient} from '@tanstack/react-query'

import LocalMediaProfileCard from '../LocalMediaProfile/LocalMediaProfileCard'
import LocalMediaProfileForm from '../LocalMediaProfile/LocalMediaProfileForm'
import {useLocalMediaProfiles} from '../../lib/queries'
import {LocalMediaProfileRead} from '../../types/schemas/local_media_profile'
import {
    DEFAULT_MOVIE_OUTPUT_TEMPLATE,
    VideoLocalMediaProfileCreateIn,
    VideoLocalMediaProfileCreateSchema,
} from '../../types/schemas/video_local_media_profile'
import {DAILYWIRE_SOURCE_KEY} from '../../types/schemas/source'
import {isLocalMediaProfileAvailableForSite, videoProfileKeeps} from '../../types/local_media_profile'
import {getErrorMessageFromResponse} from '../../utils/helpers'
import {getZodDefaults} from '../../utils/defaultZod'
import {apiUrl} from '../../lib/api'


type Props = {
    movieTitle: string
    onBack: () => void
    onContinue: (profile: LocalMediaProfileRead) => void
}

// Movies come from The Daily Wire, whose Site has its Source's key. A profile made here is only for its movies.
const MOVIE_SITE_KEY = DAILYWIRE_SOURCE_KEY

const NEW_PROFILE_DEFAULTS: VideoLocalMediaProfileCreateIn = {
    ...getZodDefaults(VideoLocalMediaProfileCreateSchema),
    name: 'My Movies',
    videoScope: 'movies',
    outputTemplate: DEFAULT_MOVIE_OUTPUT_TEMPLATE,
    subtitleMode: 'sidecar',
    siteKeys: [MOVIE_SITE_KEY],
    includeUpcomingSites: false,
}

export default function OnboardingMovieProfileStep({movieTitle, onBack, onContinue}: Props) {
    const profilesQuery = useLocalMediaProfiles()
    const queryClient = useQueryClient()
    const initialized = useRef(false)
    const [selectedSlug, setSelectedSlug] = useState<string | null>(null)

    const form = useForm<VideoLocalMediaProfileCreateIn>({
        resolver: zodResolver(VideoLocalMediaProfileCreateSchema) as any,
        mode: 'onBlur',
        shouldFocusError: true,
        defaultValues: NEW_PROFILE_DEFAULTS,
    })

    const movieProfiles = useMemo(
        () => profilesQuery.data?.filter((profile) => (
            profile.type === 'video' && videoProfileKeeps(profile, 'movies') && isLocalMediaProfileAvailableForSite(profile, MOVIE_SITE_KEY)
        )) ?? [],
        [profilesQuery.data],
    )

    const selectProfile = useCallback((profile: LocalMediaProfileRead) => {
        if (profile.type !== 'video') return
        setSelectedSlug(profile.slug)
        form.reset({
            ...getZodDefaults(VideoLocalMediaProfileCreateSchema),
            name: profile.name,
            videoScope: profile.videoScope,
            outputTemplate: profile.outputTemplate,
            preferredFormat: profile.preferredFormat as VideoLocalMediaProfileCreateIn['preferredFormat'],
            subtitleMode: profile.subtitleMode,
            siteKeys: profile.siteKeys,
            includeUpcomingSites: profile.includeUpcomingSites,
        })
    }, [form])

    useEffect(() => {
        if (initialized.current || profilesQuery.isPending || profilesQuery.isError) return
        initialized.current = true
        const starter = movieProfiles.find((profile) => profile.slug === 'vodloft-movies') ?? movieProfiles[0]
        if (starter) selectProfile(starter)
    }, [movieProfiles, profilesQuery.isError, profilesQuery.isPending, selectProfile])

    const createNew = () => {
        setSelectedSlug(null)
        form.reset(NEW_PROFILE_DEFAULTS)
    }

    const submit = form.handleSubmit(async (input) => {
        form.clearErrors('root')
        try {
            const data = VideoLocalMediaProfileCreateSchema.parse(input)
            const base = apiUrl()
            const isUpdating = selectedSlug !== null
            const response = await fetch(
                isUpdating
                    ? `${base}/video-local-media-profiles/${encodeURIComponent(selectedSlug)}`
                    : `${base}/video-local-media-profiles`,
                {
                    method: isUpdating ? 'PATCH' : 'POST',
                    credentials: 'include',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(data),
                },
            )

            if (!response.ok) {
                const {error} = await getErrorMessageFromResponse(response)
                form.setError('root', {
                    type: 'server',
                    message: error || 'Could not save the Local Media Profile.',
                })
                return
            }

            const profile = await response.json() as LocalMediaProfileRead
            await queryClient.invalidateQueries({queryKey: ['localMediaProfiles']})
            onContinue(profile)
        } catch {
            form.setError('root', {
                type: 'server',
                message: 'Could not save the Local Media Profile. Check the connection and try again.',
            })
        }
    })

    return (
        <section className="onboarding-profile-step" aria-labelledby="onboarding-movie-profile-title">
            <div className="onboarding-section-heading">
                <span className="onboarding-eyebrow">Before opening {movieTitle}</span>
                <h1 id="onboarding-movie-profile-title">Choose where movie files will be stored</h1>
                <p>
                    Select a profile to edit its values, or create another one. The profile saved here will already be
                    selected when the movie page opens.
                </p>
            </div>

            <form className="form form-fluid onboarding-profile-form" onSubmit={submit} noValidate>
                <div className="form-row">
                    <div className="onboarding-profile-list-heading">
                        <label>Local Media Profile</label>
                        <button className="btn" type="button" onClick={createNew}>Create a new profile</button>
                    </div>
                    <div className="card-grid" role="list">
                        {profilesQuery.isPending ? (
                            <div role="listitem" className="card">Loading profiles…</div>
                        ) : profilesQuery.isError ? (
                            <div role="listitem" className="card">Could not load profiles: {profilesQuery.error.message}</div>
                        ) : movieProfiles.length === 0 ? (
                            <div role="listitem" className="card selected">Create your first Local Media Profile for movies below.</div>
                        ) : (
                            movieProfiles.map((profile) => (
                                <LocalMediaProfileCard
                                    key={profile.slug}
                                    profile={profile}
                                    selected={selectedSlug === profile.slug}
                                    onClick={() => selectProfile(profile)}
                                />
                            ))
                        )}
                    </div>
                </div>

                <hr className="divider" aria-hidden="true"/>
                <div className="divider-label" aria-hidden="true">
                    {selectedSlug ? 'Edit selected profile' : 'Create a new profile'}
                </div>

                <LocalMediaProfileForm form={form} mode="video" isCreating={selectedSlug === null}/>

                <div className="actions">
                    <button className="btn" type="button" onClick={onBack}>Back</button>
                    <button
                        className="btn btn-primary"
                        type="submit"
                        disabled={form.formState.isSubmitting || profilesQuery.isPending}
                    >
                        {form.formState.isSubmitting ? 'Saving…' : 'Save and open movie'}
                    </button>
                </div>
            </form>
        </section>
    )
}
