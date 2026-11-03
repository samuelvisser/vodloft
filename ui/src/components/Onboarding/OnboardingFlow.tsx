import {useCallback, useEffect, useRef, useState} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {Route, Routes, useNavigate} from 'react-router-dom'
import {useQueryClient} from '@tanstack/react-query'
import AddCollectionPage from '../AddCollectionPage/AddCollectionPage'
import AddMediaPage from '../../pages/AddMediaPage'
import type {MediaLinkTarget} from '../../lib/sourceControls'
import BrowsePage from '../../pages/BrowsePage'
import SourceSearchPage from '../../pages/SourceSearchPage'
import MoviePage from '../../pages/movie/MoviePage'
import {useMovies, useSources} from '../../lib/queries'
import {sourceComponents} from '../Source/sourceComponents'
import SourceCookiesCard from '../Source/SourceCookiesCard'
import {ANY_DOMAIN, SourceFeature, SourceRead, sourceHas} from '../../types/schemas/source'
import {LocalMediaProfileRead} from '../../types/schemas/local_media_profile'
import {CollectionRead} from '../../types/schemas/collection'
import OnboardingMovieProfileStep from './OnboardingMovieProfileStep'
import OnboardingMediaStep from './OnboardingMediaStep'
import './Onboarding.css'
import {faIcon} from '../../icons/faIcon'


type OnboardingStep = 'welcome' | 'sources' | 'security' | 'media' | 'import' | 'add' | 'browse' | 'search' | 'collection' | 'movie-profile' | 'movie'

/** The collection or movie picked as the first media, from a link or from browsing. */
type SelectedMedia = {slug: string; title: string; url: string}

type Props = {
    adminPasswordConfigured: boolean
    /** Finish onboarding, then open ``path`` (the home page when left out). */
    onComplete: (path?: string) => void
}

/** The Source that works with any site comes first, since most people start there; the rest keep their order. */
function onboardingSourceOrder(sources: SourceRead[]): SourceRead[] {
    const anySite = (source: SourceRead) => source.domains.includes(ANY_DOMAIN)
    return [...sources.filter(anySite), ...sources.filter((source) => !anySite(source))]
}

const STEP_LABELS = ['Welcome', 'Sources', 'Security', 'Your media']

function visibleStepIndex(step: OnboardingStep) {
    if (step === 'welcome') return 0
    if (step === 'sources') return 1
    if (step === 'security') return 2
    return 3
}

export default function OnboardingFlow({adminPasswordConfigured, onComplete}: Props) {
    const navigate = useNavigate()
    const queryClient = useQueryClient()
    const {data: localMovies} = useMovies()
    const [step, setStep] = useState<OnboardingStep>('welcome')
    const {data: sources} = useSources()
    const [selectedCollection, setSelectedCollection] = useState<SelectedMedia | null>(null)
    const [selectedCollectionWasPresent, setSelectedCollectionWasPresent] = useState(false)
    const [selectedMovie, setSelectedMovie] = useState<SelectedMedia | null>(null)
    const [movieProfile, setMovieProfile] = useState<LocalMediaProfileRead | null>(null)
    const [searchSourceId, setSearchSourceId] = useState<string | null>(null)
    // A search result that is not a collection goes back to the links step, which looks it up.
    const [addUrl, setAddUrl] = useState<string | undefined>(undefined)
    const [isCompleting, setIsCompleting] = useState(false)
    const completingRef = useRef(false)
    const [error, setError] = useState<string | null>(null)

    const completeOnboarding = useCallback(async (path?: string) => {
        if (completingRef.current) return
        completingRef.current = true
        setIsCompleting(true)
        setError(null)
        try {
            const response = await fetch(`${(window as any).appConfig.API_URL}/onboarding/complete`, {
                method: 'POST',
                credentials: 'include',
            })
            if (!response.ok) throw new Error(`HTTP ${response.status}`)
            onComplete(path)
        } catch {
            setError('VODLoft could not finish onboarding. Please try again.')
        } finally {
            completingRef.current = false
            setIsCompleting(false)
        }
    }, [onComplete])

    // A fresh library gets the default Collection profiles only once its first collection needs one,
    // and loses them again when the person goes back to choose an import instead.
    const setFreshStartProfiles = async (wanted: boolean) => {
        const response = await fetch(`${(window as any).appConfig.API_URL}/onboarding/start-fresh`, {
            method: wanted ? 'POST' : 'DELETE',
            credentials: 'include',
        })
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        await queryClient.invalidateQueries({queryKey: ['localMediaProfiles']})
    }

    const backToMediaChoice = async () => {
        setAddUrl(undefined)
        try {
            await setFreshStartProfiles(false)
        } catch {
            // Finishing onboarding without an import adds them anyway, so a leftover profile does no harm.
        }
        setStep('media')
    }

    const selectCollection = async (collection: SelectedMedia) => {
        try {
            await setFreshStartProfiles(true)
        } catch {
            // The wizard still lets the person make a profile of their own.
        }
        const currentCollections = queryClient.getQueryData<CollectionRead[]>(['collections']) ?? []
        setSelectedCollectionWasPresent(currentCollections.some((item) => item.slug === collection.slug))
        setSelectedCollection(collection)
        setError(null)
        setStep('collection')
    }

    const leaveCollectionWizard = async () => {
        try {
            const response = await fetch(`${(window as any).appConfig.API_URL}/collections`, {credentials: 'include'})
            if (response.ok) {
                const currentCollections = await response.json() as CollectionRead[]
                queryClient.setQueryData(['collections'], currentCollections)
                const wasAdded = !selectedCollectionWasPresent && currentCollections.some((item) => item.slug === selectedCollection?.slug)
                if (wasAdded) {
                    await completeOnboarding()
                    return
                }
            }
        } catch {
            // Returning to the first-media step still gives the user a safe way to finish or retry setup.
        }
        setStep('add')
    }

    const selectMovie = (movie: SelectedMedia) => {
        setSelectedMovie(movie)
        setMovieProfile(null)
        setError(null)
        setStep('movie-profile')
    }

    useEffect(() => {
        if (step !== 'movie' || !selectedMovie) return
        if (localMovies?.some((movie) => movie.slug === selectedMovie.slug)) {
            void completeOnboarding()
        }
    }, [completeOnboarding, localMovies, selectedMovie, step])

    const progress = visibleStepIndex(step)
    const showTopbar = step !== 'welcome'

    return (
        <div className={`onboarding-shell onboarding-step-${step}`}>
            <div className="onboarding-backdrop" aria-hidden="true"/>

            {showTopbar && (
                <header className="onboarding-topbar">
                    <img src="/logo-wide-full.png" alt="VODLoft"/>
                    <ol className="onboarding-progress" aria-label="Onboarding progress">
                        {STEP_LABELS.map((label, index) => (
                            <li key={label} className={index === progress ? 'is-active' : index < progress ? 'is-complete' : ''}>
                                <span>{index < progress ? <FontAwesomeIcon icon={faIcon('fass', 'check')}/> : index + 1}</span>
                                <small>{label}</small>
                            </li>
                        ))}
                    </ol>
                </header>
            )}

            {error && (
                <div className="onboarding-global-error form-error-card" role="alert">
                    <span>{error}</span>
                    <button className="btn" type="button" onClick={() => void completeOnboarding()} disabled={isCompleting}>
                        Try again
                    </button>
                </div>
            )}

            {step === 'welcome' && (
                <main className="onboarding-welcome">
                    <div className="onboarding-welcome-glow" aria-hidden="true"/>
                    <img className="onboarding-welcome-logo" src="/logo-wide-full.png" alt="VODLoft"/>
                    <p>Bring your library home.</p>
                    <button className="btn btn-primary onboarding-primary-action" type="button" onClick={() => setStep('sources')}>
                        Continue
                        <FontAwesomeIcon icon={faIcon('fass', 'arrow-right')}/>
                    </button>
                </main>
            )}

            {step === 'sources' && (
                <main className="onboarding-stage onboarding-stage-narrow">
                    <div className="onboarding-section-heading">
                        <span className="onboarding-eyebrow">Sources</span>
                        <h1>Where your media comes from</h1>
                        <p>
                            VODLoft adds collections and movies from these services. Signing in or adding a cookies file
                            is optional: it is only needed for content that requires an account, and you can do it later in
                            Settings › Sources.
                        </p>
                    </div>
                    {onboardingSourceOrder(sources ?? []).map((source) => {
                        const {SignIn} = sourceComponents(source.id)
                        const canSignIn = sourceHas(source, SourceFeature.LOGIN) && SignIn
                        const takesCookies = sourceHas(source, SourceFeature.COOKIES)
                        return (
                            <details className="onboarding-source" key={source.id} open={(sources?.length ?? 0) === 1}>
                                <summary>
                                    <strong>{source.sitesLabel ? `${source.name} (${source.sitesLabel})` : source.name}</strong>
                                    <small>
                                        {canSignIn ? 'Optional sign-in' : takesCookies ? 'Optional cookies file' : 'No sign-in needed'}
                                    </small>
                                </summary>
                                {canSignIn ? <SignIn/> : null}
                                {takesCookies ? <SourceCookiesCard source={source}/> : null}
                            </details>
                        )
                    })}
                    <div className="onboarding-stage-actions">
                        <button className="btn" type="button" onClick={() => setStep('welcome')}>Back</button>
                        <button className="btn btn-primary" type="button" onClick={() => setStep('security')}>
                            Continue
                        </button>
                    </div>
                </main>
            )}

            {step === 'security' && (
                <main className="onboarding-stage onboarding-stage-narrow">
                    <div className="onboarding-section-heading">
                        <span className="onboarding-eyebrow">Protect VODLoft</span>
                        <h1>Create an administrator password</h1>
                        <p>
                            Set the environment variable below on your VODLoft container and restart it. This is
                            especially important when VODLoft is reachable through a reverse proxy.
                        </p>
                    </div>

                    <div className={`onboarding-security-card${adminPasswordConfigured ? ' is-configured' : ''}`}>
                        <div className="onboarding-security-icon" aria-hidden="true">
                            {adminPasswordConfigured
                                ? <FontAwesomeIcon icon={faIcon('fass', 'shield-halved')}/>
                                : <FontAwesomeIcon icon={faIcon('fass', 'triangle-exclamation')}/>}
                        </div>
                        <div>
                            <strong>{adminPasswordConfigured ? 'Administrator authentication is configured' : 'Administrator authentication is not configured yet'}</strong>
                            <p>
                                {adminPasswordConfigured
                                    ? 'VODLoft will require the administrator password before showing protected pages.'
                                    : 'Without this value, anyone who can reach VODLoft can control it and access its stored account session.'}
                            </p>
                        </div>
                    </div>

                    <div className="onboarding-env-example">
                        <div>
                            <span>Environment variable</span>
                            <code>VL_ADMIN_AUTH__PASSWORD</code>
                        </div>
                        <pre><code>{'environment:\n  VL_ADMIN_AUTH__PASSWORD: "choose-a-long-unique-password"'}</code></pre>
                    </div>

                    <p className="onboarding-security-note">
                        A restart is required after changing the variable. On the next visit, VODLoft will show its own
                        administrator login before loading the application.
                    </p>

                    <p className="onboarding-security-note">
                        Sharing VODLoft with others? Later, turn on user accounts in Settings › Users to give each
                        person their own sign-in with only the parts they need, such as just Quick download.
                    </p>

                    <div className="onboarding-stage-actions">
                        <button className="btn" type="button" onClick={() => setStep('sources')}>Back</button>
                        <button className="btn btn-primary" type="button" onClick={() => setStep('media')}>
                            Continue to library setup
                        </button>
                    </div>
                </main>
            )}

            {(step === 'media' || step === 'import') && (
                <main className="onboarding-stage onboarding-stage-narrow">
                    <OnboardingMediaStep
                        importing={step === 'import'}
                        onBack={() => setStep(step === 'import' ? 'media' : 'security')}
                        onImport={() => setStep('import')}
                        onStartFresh={() => setStep('add')}
                        onImported={(path) => void completeOnboarding(path)}
                    />
                    {isCompleting && <div className="onboarding-completing" role="status">Finishing setup…</div>}
                </main>
            )}

            {step === 'add' && (
                <main className="onboarding-stage onboarding-stage-wide">
                    <AddMediaPage
                        onboarding
                        initialUrl={addUrl}
                        onCollection={(target: MediaLinkTarget) => void selectCollection(target)}
                        onMovie={(target: MediaLinkTarget) => selectMovie(target)}
                        onBrowse={(sourceId) => {
                            const source = sources?.find((item) => item.id === sourceId)
                            if (sourceHas(source, SourceFeature.BROWSE)) {
                                setStep('browse')
                                return
                            }
                            setSearchSourceId(sourceId)
                            setStep('search')
                        }}
                        onBack={() => void backToMediaChoice()}
                        onSkip={() => void completeOnboarding()}
                    />
                    {isCompleting && <div className="onboarding-completing" role="status">Finishing setup…</div>}
                </main>
            )}

            {step === 'browse' && (
                <main className="onboarding-stage">
                    <button className="btn onboarding-movie-back" type="button" onClick={() => setStep('add')}>
                        <FontAwesomeIcon icon={faIcon('fass', 'arrow-left')}/> Back to links
                    </button>
                    <BrowsePage
                        onboarding
                        onCollectionSelect={(collection, url) => void selectCollection({slug: collection.slug, title: collection.title, url})}
                        onMovieSelect={(movie, url) => selectMovie({slug: movie.slug, title: movie.title, url})}
                        onSkip={() => void completeOnboarding()}
                    />
                    {isCompleting && <div className="onboarding-completing" role="status">Finishing setup…</div>}
                </main>
            )}

            {step === 'search' && searchSourceId && (
                <main className="onboarding-stage onboarding-stage-narrow">
                    <button className="btn onboarding-movie-back" type="button" onClick={() => setStep('add')}>
                        <FontAwesomeIcon icon={faIcon('fass', 'arrow-left')}/> Back to links
                    </button>
                    <SourceSearchPage
                        sourceId={searchSourceId}
                        onChoose={(result) => {
                            if (result.kind === 'collection') {
                                void selectCollection({slug: result.slug, title: result.title, url: result.url})
                                return
                            }
                            setAddUrl(result.url)
                            setStep('add')
                        }}
                    />
                </main>
            )}

            {step === 'collection' && selectedCollection && (
                <main className="onboarding-stage onboarding-stage-wide onboarding-wizard-stage">
                    <div className="onboarding-section-heading onboarding-nested-heading">
                        <span className="onboarding-eyebrow">Add your first collection</span>
                        <h1>{selectedCollection.title}</h1>
                        <p>The normal Add Collection wizard will let you confirm a Local Media Profile before any downloads are configured.</p>
                    </div>
                    <AddCollectionPage
                        initialUrl={selectedCollection.url}
                        onCancel={() => void leaveCollectionWizard()}
                    />
                </main>
            )}

            {step === 'movie-profile' && selectedMovie && (
                <main className="onboarding-stage onboarding-stage-wide">
                    <OnboardingMovieProfileStep
                        movieTitle={selectedMovie.title}
                        onBack={() => {
                            navigate('/?type=movies', {replace: true})
                            setStep('add')
                        }}
                        onContinue={(profile) => {
                            queryClient.setQueryData<LocalMediaProfileRead[]>(['localMediaProfiles'], (current) => {
                                const remaining = (current ?? []).filter((item) => item.id !== profile.id)
                                return [profile, ...remaining]
                            })
                            setMovieProfile(profile)
                            navigate(`/movie/${selectedMovie.slug}`, {replace: true})
                            setStep('movie')
                        }}
                    />
                </main>
            )}

            {step === 'movie' && selectedMovie && movieProfile && (
                <main className="onboarding-stage onboarding-stage-movie">
                    <button
                        className="btn onboarding-movie-back"
                        type="button"
                        onClick={() => setStep('movie-profile')}
                    >
                        <FontAwesomeIcon icon={faIcon('fass', 'arrow-left')}/> Back to profile
                    </button>
                    <Routes>
                        <Route path="/movie/:slug" element={<MoviePage/>}/>
                    </Routes>
                    {isCompleting && <div className="onboarding-completing" role="status">Finishing setup…</div>}
                </main>
            )}
        </div>
    )
}
