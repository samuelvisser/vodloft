import {useEffect, useMemo, useRef, useState} from 'react'
import {getCurrentAppVersion, getErrorMessageFromResponse} from '../../utils/helpers'
import ChooseShowStep from './ChooseShowStep'
import ShowActionStep, {ShowAction} from './ShowActionStep'
import LocalMediaProfileStep from './LocalMediaProfileStep'
import DownloadProfileStep from './DownloadProfileStep'
import StreamProfileStep from './StreamProfileStep'

import type {Versioned} from '../../types/data'
import {ShowCreatePayloadOut, ShowCreatePayloadIn, ShowCreatePayloadSchema} from "../../types/schemas/show";
import {getZodDefaults} from "../../utils/defaultZod";
import {
    DownloadProfileBundleSchema, DownloadProfileBundleIn, DownloadProfileBundleOut,
    LocalMediaProfileCreateUnionSchema,
    LocalMediaProfileUpsertIn,
    LocalMediaProfileUpsertOut,
    RssStreamProfileBundleIn,
    RssStreamProfileBundleOut,
} from "../../types/schemas/show_as_bundle";
import {downloadProfileDefaultsFor} from "../../types/schemas/download_profile";
import {useQueryClient} from "@tanstack/react-query";
import {SeasonDetachedOut} from "../../types/schemas/season";
import {useEpisodeTags, useSourceLookup} from "../../lib/queries";
import {EpisodeTagRead, SourceFeature, sourceHas} from "../../types/schemas/source";

export type Props = {
    onCancel: () => void
    initialUrl?: string
}

const STORAGE_KEY = 'addShowWizardV10'

type WizardType = 'ERROR' | 'INFO'
type WizardMessage = { text: string; type: WizardType }
type WizardStep = 1 | 2 | 3 | 4 | 5

type WizardState = {
    step: WizardStep
    action?: ShowAction
    show: {
        input: Partial<ShowCreatePayloadIn>,
        submit: ShowCreatePayloadOut | undefined,
    },
    localMediaProfile: {
        input: Partial<LocalMediaProfileUpsertIn>,
        submit: LocalMediaProfileUpsertOut | undefined,
    },
    downloadProfile: {
        input: Partial<DownloadProfileBundleIn>,
        submit: DownloadProfileBundleOut | undefined,
    }
    streamProfile: {
        input: Partial<RssStreamProfileBundleIn>,
        submit: RssStreamProfileBundleOut | undefined,
        episodeTypesManuallyChanged?: boolean,
    }
    seasons: SeasonDetachedOut[] | undefined,
    globalMessage?: WizardMessage | null
}

function loadWizardState(): WizardState | null {
    try {
        const raw = localStorage.getItem(STORAGE_KEY)
        if (!raw) return null
        const parsed = JSON.parse(raw) as any
        const current = getCurrentAppVersion()
        if (parsed && typeof parsed === 'object' && 'version' in parsed && 'data' in parsed) {
            if (typeof current === 'string') {
                if (parsed.version === current) return parsed.data as WizardState
                localStorage.removeItem(STORAGE_KEY)
                return null
            }
            return null
        }
        if (typeof current === 'string') localStorage.removeItem(STORAGE_KEY)
        return null
    } catch {
        return null
    }
}

function saveWizardState(state: WizardState) {
    try {
        const ver = getCurrentAppVersion()
        if (!ver) return
        const payload: Versioned<WizardState> = {version: ver, data: state}
        localStorage.setItem(STORAGE_KEY, JSON.stringify(payload))
    } catch {
        // ignore write errors
    }
}

function clearWizardState() {
    try {
        localStorage.removeItem(STORAGE_KEY)
    } catch {
        // ignore
    }
}

const defaultDownloadProfile = (episodeIdentifier?: string, tags?: EpisodeTagRead[]): Partial<DownloadProfileBundleIn> => ({
    ...getZodDefaults(DownloadProfileBundleSchema),
    ...downloadProfileDefaultsFor(episodeIdentifier, tags),
})

const showTagsKey = (show?: ShowCreatePayloadOut) => (show ? `${show.sourceKey} ${show.sharingUrl}` : undefined)

const defaultStreamProfile = (action?: ShowAction): Partial<RssStreamProfileBundleIn> => ({
    enableProfile: true,
    useDownloads: true,
    useDwStream: action === 'stream',
    preferredFormat: 'format_1080p',
    preferExactMatch: false,
    epIdTypeList: ['ep', 'aux'],
})

export default function AddShowPage({onCancel, initialUrl}: Props) {
    const persisted = initialUrl ? null : loadWizardState()
    const [globalMessage, setGlobalMessage] = useState<WizardMessage | null>(() => persisted?.globalMessage ?? null)
    const [isFinishing, setIsFinishing] = useState(false)
    const setWizardMessage = (message: string, type: WizardType) => setGlobalMessage({text: message, type})
    const clearWizardMessage = () => setGlobalMessage(null)
    const qc = useQueryClient()
    const sources = useSourceLookup()

    const [step, setStep] = useState<WizardStep>(() => persisted?.step ?? 1)
    const previousStepRef = useRef(step)
    const [showAction, setShowAction] = useState<ShowAction | undefined>(() => persisted?.action)

    const [showInput, setShowInput] = useState<Partial<ShowCreatePayloadIn>>(
        () => ({
            ...(persisted?.show.input ?? getZodDefaults(ShowCreatePayloadSchema)),
            ...(initialUrl ? {url: initialUrl} : {}),
        }))
    const [showSubmit, setShowSubmit] = useState<ShowCreatePayloadOut | undefined>(() => persisted?.show.submit)

    const [localMediaProfileInput, setLocalMediaProfileInput] = useState<Partial<LocalMediaProfileUpsertIn>>(
        () => persisted?.localMediaProfile.input ?? getZodDefaults(LocalMediaProfileCreateUnionSchema))
    const [localMediaProfileSubmit, setLocalMediaProfileSubmit] = useState<LocalMediaProfileUpsertOut | undefined>(() => persisted?.localMediaProfile.submit)

    const [downloadProfileInput, setDownloadProfileInput] = useState<Partial<DownloadProfileBundleIn>>(
        () => persisted?.downloadProfile.input ?? defaultDownloadProfile(persisted?.show.submit?.episodeIdentifier))
    const [downloadProfileSubmit, setDownloadProfileSubmit] = useState<DownloadProfileBundleOut | undefined>(() => persisted?.downloadProfile.submit)

    const [streamProfileInput, setStreamProfileInput] = useState<Partial<RssStreamProfileBundleIn>>(
        () => persisted?.streamProfile?.input ?? defaultStreamProfile(persisted?.action))
    const [streamProfileSubmit, setStreamProfileSubmit] = useState<RssStreamProfileBundleOut | undefined>(
        () => persisted?.streamProfile?.submit)
    const [streamEpisodeTypesManuallyChanged, setStreamEpisodeTypesManuallyChanged] = useState(
        () => persisted?.streamProfile?.episodeTypesManuallyChanged ?? false
    )

    const [seasonsSubmit, setSeasonsSubmit] = useState<SeasonDetachedOut[] | undefined>(() => persisted?.seasons ?? [])

    // The episode tags to download by default come from the show's Source once the show is chosen.
    const {data: showEpisodeTags} = useEpisodeTags(showSubmit?.sourceKey, showSubmit?.sharingUrl)
    const tagDefaultsAppliedFor = useRef(persisted?.downloadProfile.input ? showTagsKey(persisted?.show.submit) : undefined)
    useEffect(() => {
        const key = showTagsKey(showSubmit)
        if (!showSubmit || !showEpisodeTags || downloadProfileSubmit || tagDefaultsAppliedFor.current === key) return
        tagDefaultsAppliedFor.current = key
        const {epIdTypeList} = downloadProfileDefaultsFor(showSubmit.episodeIdentifier, showEpisodeTags)
        setDownloadProfileInput((current) => ({...current, epIdTypeList}))
    }, [downloadProfileSubmit, showEpisodeTags, showSubmit])

    const downloadProfileSubmitRef = useRef(downloadProfileSubmit)
    const streamProfileSubmitRef = useRef(streamProfileSubmit)

    const wizardDownloadProfileDefaults = useMemo(() => {
        if (!localMediaProfileSubmit || !downloadProfileSubmit) return []
        return [{
            preferredFormat: localMediaProfileSubmit.preferredFormat,
            episodeTypes: downloadProfileSubmit.epIdTypeList,
            enabled: downloadProfileSubmit.enableProfile,
        }]
    }, [localMediaProfileSubmit, downloadProfileSubmit])

    useEffect(() => {
        const previousStep = previousStepRef.current
        previousStepRef.current = step
        if (step <= previousStep) return

        // Scroll to the top of the page rather than the wizard itself, so the sticky mobile header
        // can't cover the first field of the next step.
        window.scrollTo({top: 0, behavior: 'auto'})
    }, [step])

    useEffect(() => {
        saveWizardState({
            step,
            action: showAction,
            show: {input: showInput, submit: showSubmit},
            localMediaProfile: {input: localMediaProfileInput, submit: localMediaProfileSubmit},
            downloadProfile: {input: downloadProfileInput, submit: downloadProfileSubmit},
            streamProfile: {
                input: streamProfileInput,
                submit: streamProfileSubmit,
                episodeTypesManuallyChanged: streamEpisodeTypesManuallyChanged,
            },
            seasons: seasonsSubmit,
            globalMessage,
        })
    }, [step, showAction, showInput, showSubmit, localMediaProfileInput, localMediaProfileSubmit,
        downloadProfileInput, downloadProfileSubmit, streamProfileInput, streamProfileSubmit, streamEpisodeTypesManuallyChanged,
        seasonsSubmit, globalMessage])

    function handleCancel() {
        clearWizardState()
        onCancel()
    }

    async function handleFinish(actionOverride?: ShowAction) {
        const action = actionOverride ?? showAction
        const show = showSubmit
        const seasons = seasonsSubmit

        if (!action || !show || !seasons) {
            setWizardMessage('The show setup is incomplete. Please go back and complete the previous steps.', 'ERROR')
            return
        }

        let localMediaProfile: LocalMediaProfileUpsertOut | undefined
        let downloadProfile: DownloadProfileBundleOut | undefined
        let streamProfile: RssStreamProfileBundleOut | undefined

        if (action === 'download' || action === 'download-stream') {
            localMediaProfile = localMediaProfileSubmit
            if (!localMediaProfile) {
                setWizardMessage('Please complete the Media Profile step before finishing.', 'ERROR')
                return
            }
            downloadProfile = downloadProfileSubmitRef.current ?? downloadProfileSubmit
            if (!downloadProfile) {
                setWizardMessage('Please complete the Download Profile step before finishing.', 'ERROR')
                return
            }
        }

        if (action === 'stream' || action === 'download-stream') {
            streamProfile = streamProfileSubmitRef.current ?? streamProfileSubmit
            if (!streamProfile) {
                setWizardMessage('Please complete the Stream Profile step before finishing.', 'ERROR')
                return
            }
        }

        setIsFinishing(true)
        setWizardMessage('Saving show...', 'INFO')

        const submitData = {
            show,
            seasons,
            ...(localMediaProfile ? {localMediaProfile} : {}),
            ...(downloadProfile ? {downloadProfile} : {}),
            ...(streamProfile ? {streamProfile} : {}),
        }

        try {
            const response = await fetch(`${(window as any).appConfig.API_URL}/shows/as-bundle`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                credentials: 'include',
                body: JSON.stringify(submitData),
            })

            if (response.status !== 201) {
                let {error} = await getErrorMessageFromResponse(response)
                if (response.status === 409) error = 'This show already exists'
                setWizardMessage(error ?? `HTTP ${response.status}`, 'ERROR')
                return
            }
            clearWizardMessage()
        } catch {
            setWizardMessage('Network error, please try again.', 'ERROR')
            return
        } finally {
            setIsFinishing(false)
        }

        await Promise.all([
            qc.invalidateQueries({queryKey: ['localMediaProfiles']}),
            qc.invalidateQueries({queryKey: ['downloadProfiles']}),
            qc.invalidateQueries({queryKey: ['rssStreamProfiles']}),
            qc.invalidateQueries({queryKey: ['streamProfilesView']}),
            qc.invalidateQueries({queryKey: ['shows']}),
            qc.invalidateQueries({queryKey: ['seasons']}),
        ])
        clearWizardState()
        onCancel()
    }

    async function handleActionContinue() {
        if (!showAction) return
        if (showAction === 'index') {
            await handleFinish('index')
            return
        }
        if (showAction === 'stream' || showAction === 'download-stream') {
            setStreamProfileInput((current) => ({...defaultStreamProfile(showAction), ...current,
                useDownloads: true,
                useDwStream: showAction === 'stream',
            }))
        }
        setStep(3)
    }

    const totalSteps = showAction === 'download-stream' ? 5 : showAction === 'download' ? 4 : showAction === 'stream' ? 3 : 2
    const stepTitle = step === 1 ? 'Choose show'
        : step === 2 ? 'Choose what VODLoft should do'
        : showAction === 'stream' ? 'Stream Profile'
        : step === 3 ? 'Media Profile'
        : step === 4 ? 'Download Profile'
        : 'Stream Profile'

    return (
        <div>
            {globalMessage && (
                <div
                    className={globalMessage.type === 'ERROR' ? 'form-error-card' : 'form-info-card'}
                    role="alert"
                    aria-live="polite"
                    style={{marginBottom: 12}}
                >
                    {globalMessage.text}
                </div>
            )}

            <div className="help" aria-live="polite" style={{marginBottom: 12}}>
                Step {step} of {totalSteps}: {stepTitle}
            </div>

            {step === 1 && (
                <ChooseShowStep
                    value={showInput}
                    onChange={setShowInput}
                    onSubmit={(value) => {
                        if (showSubmit?.type && showSubmit.type !== value.type) {
                            setLocalMediaProfileInput(getZodDefaults(LocalMediaProfileCreateUnionSchema))
                            setLocalMediaProfileSubmit(undefined)
                        }
                        // The download options follow how the show identifies its episodes, and its Source's episode tags.
                        if (showSubmit?.episodeIdentifier !== value.episodeIdentifier || showTagsKey(showSubmit) !== showTagsKey(value)) {
                            const tags = qc.getQueryData<EpisodeTagRead[]>(['episodeTags', value.sourceKey, value.sharingUrl])
                            setDownloadProfileInput(defaultDownloadProfile(value.episodeIdentifier, tags))
                            if (!tags) tagDefaultsAppliedFor.current = undefined
                            setDownloadProfileSubmit(undefined)
                            downloadProfileSubmitRef.current = undefined
                        }
                        setShowSubmit(value)
                    }}
                    onSeasonsSubmit={setSeasonsSubmit}
                    onContinue={() => setStep(2)}
                    onCancel={handleCancel}
                />
            )}

            {step === 2 && (
                <ShowActionStep
                    value={showAction}
                    canStreamFromSource={!showSubmit || sourceHas(sources.get(showSubmit.sourceKey), SourceFeature.RSS_STREAMING)}
                    onChange={setShowAction}
                    onBack={() => setStep(1)}
                    onContinue={handleActionContinue}
                    onCancel={handleCancel}
                    isSubmitting={isFinishing}
                />
            )}

            {step === 3 && showAction === 'stream' && (
                <StreamProfileStep
                    value={streamProfileInput}
                    onChange={setStreamProfileInput}
                    onSubmit={(value) => {
                        setStreamProfileSubmit(value)
                        streamProfileSubmitRef.current = value
                    }}
                    onBack={() => setStep(2)}
                    onFinish={() => handleFinish('stream')}
                    onCancel={handleCancel}
                    showSlug={showSubmit?.slug}
                    show={showSubmit}
                    showTitle={showSubmit?.title}
                    downloadProfileDefaults={[]}
                    episodeTypesManuallyChanged={streamEpisodeTypesManuallyChanged}
                    onEpisodeTypesManuallyChanged={() => setStreamEpisodeTypesManuallyChanged(true)}
                />
            )}

            {step === 3 && showSubmit && (showAction === 'download' || showAction === 'download-stream') && (
                <LocalMediaProfileStep
                    value={localMediaProfileInput}
                    onChange={setLocalMediaProfileInput}
                    onSubmit={(value) => {
                        setLocalMediaProfileSubmit(value)
                        if (showAction === 'download-stream') {
                            setStreamProfileInput((current) => ({
                                ...current,
                                preferredFormat: value.preferredFormat,
                            }))
                        }
                    }}
                    onBack={() => setStep(2)}
                    onContinue={() => setStep(4)}
                    onCancel={handleCancel}
                    showSlug={showSubmit.slug}
                    show={showSubmit}
                    showType={showSubmit.type}
                />
            )}

            {step === 4 && (showAction === 'download' || showAction === 'download-stream') && (
                <DownloadProfileStep
                    value={downloadProfileInput}
                    onChange={setDownloadProfileInput}
                    onSubmit={(value) => {
                        setDownloadProfileSubmit(value)
                        downloadProfileSubmitRef.current = value
                    }}
                    onBack={() => setStep(3)}
                    onContinue={() => {
                        if (showAction === 'download') {
                            void handleFinish('download')
                            return
                        }
                        setStep(5)
                    }}
                    onCancel={handleCancel}
                    show={showSubmit}
                    seasons={seasonsSubmit ?? []}
                    continueLabel={showAction === 'download' ? 'Save show' : 'Continue'}
                />
            )}

            {step === 5 && showAction === 'download-stream' && (
                <StreamProfileStep
                    value={streamProfileInput}
                    onChange={setStreamProfileInput}
                    onSubmit={(value) => {
                        setStreamProfileSubmit(value)
                        streamProfileSubmitRef.current = value
                    }}
                    onBack={() => setStep(4)}
                    onFinish={() => handleFinish('download-stream')}
                    onCancel={handleCancel}
                    showSlug={showSubmit?.slug}
                    show={showSubmit}
                    showTitle={showSubmit?.title}
                    downloadProfileDefaults={wizardDownloadProfileDefaults}
                    episodeTypesManuallyChanged={streamEpisodeTypesManuallyChanged}
                    onEpisodeTypesManuallyChanged={() => setStreamEpisodeTypesManuallyChanged(true)}
                />
            )}
        </div>
    )
}
