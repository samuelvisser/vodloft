import {useEffect, useMemo, useRef, useState} from 'react'
import {getCurrentAppVersion, getErrorMessageFromResponse} from '../../utils/helpers'
import ChooseCollectionStep from './ChooseCollectionStep'
import CollectionActionStep, {CollectionAction} from './CollectionActionStep'
import LocalMediaProfileStep from './LocalMediaProfileStep'
import DownloadProfileStep from './DownloadProfileStep'
import StreamProfileStep from './StreamProfileStep'
import ExistingFilesStep, {defaultExistingFilesFolder, type ExistingFilesChoice} from './ExistingFilesStep'
import {layoutTemplate} from '../ExistingFiles/ExistingFilesSetup'
import {useNavigate} from 'react-router-dom'

import type {Versioned} from '../../types/data'
import {CollectionCreatePayloadOut, CollectionCreatePayloadIn, CollectionCreatePayloadSchema} from "../../types/schemas/collection";
import {getZodDefaults} from "../../utils/defaultZod";
import {
    DownloadProfileBundleSchema, DownloadProfileBundleIn, DownloadProfileBundleOut,
    LocalMediaProfileCreateUnionSchema,
    LocalMediaProfileUpsertIn,
    LocalMediaProfileUpsertOut,
    RssStreamProfileBundleIn,
    RssStreamProfileBundleOut,
} from "../../types/schemas/collection_as_bundle";
import {defaultEpisodeFilters} from "../../types/schemas/download_profile";
import {downloadedEpisodeTypes} from "../DownloadProfile/episodeFilters";
import {useQueryClient} from "@tanstack/react-query";
import {SeasonDetachedOut} from "../../types/schemas/season";
import {useEpisodeTags, useSourceLookup} from "../../lib/queries";
import {EpisodeTagRead, SourceFeature, sourceHas} from "../../types/schemas/source";
import {CollectionExamplesContext, useCollectionExamplesQuery} from "../../lib/collectionExamples";

export type Props = {
    onCancel: () => void
    initialUrl?: string
}

const STORAGE_KEY = 'addCollectionWizardV11'

type WizardType = 'ERROR' | 'INFO'
type WizardMessage = { text: string; type: WizardType }
type WizardStep = 1 | 2 | 3 | 4 | 5 | 6

type WizardState = {
    step: WizardStep
    action?: CollectionAction
    collection: {
        input: Partial<CollectionCreatePayloadIn>,
        submit: CollectionCreatePayloadOut | undefined,
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
    existingFiles?: ExistingFilesChoice,
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

/** The seasons come oldest first; a new profile starts with the latest one. */
const latestSeasonSlug = (seasons?: SeasonDetachedOut[]) => seasons?.[seasons.length - 1]?.slug

const defaultDownloadProfile = (episodeIdentifier?: string, tags?: EpisodeTagRead[], seasons?: SeasonDetachedOut[]): Partial<DownloadProfileBundleIn> => ({
    ...getZodDefaults(DownloadProfileBundleSchema),
    filters: defaultEpisodeFilters(episodeIdentifier, tags, latestSeasonSlug(seasons)),
})

const collectionTagsKey = (collection?: CollectionCreatePayloadOut) => (collection ? `${collection.sourceKey} ${collection.sharingUrl}` : undefined)
/** The starting filters follow the collection's Source tags and its latest season. */
const filterDefaultsKey = (collection?: CollectionCreatePayloadOut, seasons?: SeasonDetachedOut[]) => (
    collection ? `${collectionTagsKey(collection)} ${latestSeasonSlug(seasons) ?? ''}` : undefined
)

const defaultStreamProfile = (action?: CollectionAction): Partial<RssStreamProfileBundleIn> => ({
    enableProfile: true,
    useDownloads: true,
    useDwStream: action === 'stream',
    preferredFormat: 'format_1080p',
    preferExactMatch: false,
    epIdTypeList: ['ep', 'aux'],
})

export default function AddCollectionPage({onCancel, initialUrl}: Props) {
    const persisted = initialUrl ? null : loadWizardState()
    const [globalMessage, setGlobalMessage] = useState<WizardMessage | null>(() => persisted?.globalMessage ?? null)
    const [isFinishing, setIsFinishing] = useState(false)
    const setWizardMessage = (message: string, type: WizardType) => setGlobalMessage({text: message, type})
    const clearWizardMessage = () => setGlobalMessage(null)
    const qc = useQueryClient()
    const navigate = useNavigate()
    const sources = useSourceLookup()

    const [step, setStep] = useState<WizardStep>(() => persisted?.step ?? 1)
    const previousStepRef = useRef(step)
    const [collectionAction, setCollectionAction] = useState<CollectionAction | undefined>(() => persisted?.action)

    const [collectionInput, setCollectionInput] = useState<Partial<CollectionCreatePayloadIn>>(
        () => ({
            ...(persisted?.collection.input ?? getZodDefaults(CollectionCreatePayloadSchema)),
            ...(initialUrl ? {url: initialUrl} : {}),
        }))
    const [collectionSubmit, setCollectionSubmit] = useState<CollectionCreatePayloadOut | undefined>(() => persisted?.collection.submit)

    const [localMediaProfileInput, setLocalMediaProfileInput] = useState<Partial<LocalMediaProfileUpsertIn>>(
        () => persisted?.localMediaProfile.input ?? getZodDefaults(LocalMediaProfileCreateUnionSchema))
    const [localMediaProfileSubmit, setLocalMediaProfileSubmit] = useState<LocalMediaProfileUpsertOut | undefined>(() => persisted?.localMediaProfile.submit)

    const [downloadProfileInput, setDownloadProfileInput] = useState<Partial<DownloadProfileBundleIn>>(
        () => persisted?.downloadProfile.input ?? defaultDownloadProfile(persisted?.collection.submit?.episodeIdentifier))
    const [downloadProfileSubmit, setDownloadProfileSubmit] = useState<DownloadProfileBundleOut | undefined>(() => persisted?.downloadProfile.submit)

    const [streamProfileInput, setStreamProfileInput] = useState<Partial<RssStreamProfileBundleIn>>(
        () => persisted?.streamProfile?.input ?? defaultStreamProfile(persisted?.action))
    const [streamProfileSubmit, setStreamProfileSubmit] = useState<RssStreamProfileBundleOut | undefined>(
        () => persisted?.streamProfile?.submit)
    const [streamEpisodeTypesManuallyChanged, setStreamEpisodeTypesManuallyChanged] = useState(
        () => persisted?.streamProfile?.episodeTypesManuallyChanged ?? false
    )

    const [seasonsSubmit, setSeasonsSubmit] = useState<SeasonDetachedOut[] | undefined>(() => persisted?.seasons ?? [])
    const [existingFiles, setExistingFiles] = useState<ExistingFilesChoice>(
        () => persisted?.existingFiles ?? {enabled: false, folder: '', template: ''},
    )

    // The filters to start with come from the show's Source and seasons once the show is chosen.
    const {data: collectionEpisodeTags} = useEpisodeTags(collectionSubmit?.sourceKey, collectionSubmit?.sharingUrl)
    const tagDefaultsAppliedFor = useRef(persisted?.downloadProfile.input ? filterDefaultsKey(persisted?.collection.submit, persisted?.seasons) : undefined)
    useEffect(() => {
        const key = filterDefaultsKey(collectionSubmit, seasonsSubmit)
        if (!collectionSubmit || !collectionEpisodeTags || downloadProfileSubmit || tagDefaultsAppliedFor.current === key) return
        tagDefaultsAppliedFor.current = key
        const filters = defaultEpisodeFilters(collectionSubmit.episodeIdentifier, collectionEpisodeTags, latestSeasonSlug(seasonsSubmit))
        setDownloadProfileInput((current) => ({...current, filters}))
    }, [downloadProfileSubmit, collectionEpisodeTags, collectionSubmit, seasonsSubmit])

    const downloadProfileSubmitRef = useRef(downloadProfileSubmit)
    const streamProfileSubmitRef = useRef(streamProfileSubmit)

    const wizardDownloadProfileDefaults = useMemo(() => {
        if (!localMediaProfileSubmit || !downloadProfileSubmit) return []
        return [{
            preferredFormat: localMediaProfileSubmit.preferredFormat,
            episodeTypes: downloadedEpisodeTypes(downloadProfileSubmit.filters),
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
            action: collectionAction,
            collection: {input: collectionInput, submit: collectionSubmit},
            localMediaProfile: {input: localMediaProfileInput, submit: localMediaProfileSubmit},
            downloadProfile: {input: downloadProfileInput, submit: downloadProfileSubmit},
            streamProfile: {
                input: streamProfileInput,
                submit: streamProfileSubmit,
                episodeTypesManuallyChanged: streamEpisodeTypesManuallyChanged,
            },
            seasons: seasonsSubmit,
            existingFiles,
            globalMessage,
        })
    }, [existingFiles, step, collectionAction, collectionInput, collectionSubmit, localMediaProfileInput, localMediaProfileSubmit,
        downloadProfileInput, downloadProfileSubmit, streamProfileInput, streamProfileSubmit, streamEpisodeTypesManuallyChanged,
        seasonsSubmit, globalMessage])

    function handleCancel() {
        clearWizardState()
        onCancel()
    }

    async function handleFinish(actionOverride?: CollectionAction) {
        const action = actionOverride ?? collectionAction
        const collection = collectionSubmit
        const seasons = seasonsSubmit

        if (!action || !collection || !seasons) {
            setWizardMessage('The collection setup is incomplete. Please go back and complete the previous steps.', 'ERROR')
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
        setWizardMessage('Saving collection...', 'INFO')

        const submitData = {
            collection,
            seasons,
            ...(localMediaProfile ? {localMediaProfile} : {}),
            ...(downloadProfile ? {downloadProfile} : {}),
            ...(streamProfile ? {streamProfile} : {}),
            ...(downloadProfile && existingFiles.enabled ? {
                existingFiles: {
                    folder: existingFiles.folder.trim(),
                    template: layoutTemplate(existingFiles.folder.trim(), existingFiles.template),
                },
            } : {}),
        }

        try {
            const response = await fetch(`${(window as any).appConfig.API_URL}/collections/as-bundle`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                credentials: 'include',
                body: JSON.stringify(submitData),
            })

            if (response.status !== 201) {
                let {error} = await getErrorMessageFromResponse(response)
                if (response.status === 409) error = 'This collection already exists'
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
            qc.invalidateQueries({queryKey: ['collections']}),
            qc.invalidateQueries({queryKey: ['seasons']}),
        ])
        clearWizardState()
        if (downloadProfile && existingFiles.enabled) {
            // The scan waits for the episodes; its review opens on the collection's page.
            navigate(`/collection/${encodeURIComponent(collection.slug)}?existingFiles=open`)
            return
        }
        onCancel()
    }

    async function handleActionContinue() {
        if (!collectionAction) return
        if (collectionAction === 'index') {
            await handleFinish('index')
            return
        }
        if (collectionAction === 'stream' || collectionAction === 'download-stream') {
            setStreamProfileInput((current) => ({...defaultStreamProfile(collectionAction), ...current,
                useDownloads: true,
                useDwStream: collectionAction === 'stream',
            }))
        }
        setStep(3)
    }

    // The newest episodes serve as examples in the later steps; they load in the background.
    const examples = useCollectionExamplesQuery(collectionSubmit, seasonsSubmit)

    const totalSteps = collectionAction === 'download-stream' ? 6 : collectionAction === 'download' ? 5 : collectionAction === 'stream' ? 3 : 2
    const stepTitle = step === 1 ? 'Choose collection'
        : step === 2 ? 'Choose what VODLoft should do'
        : collectionAction === 'stream' ? 'Stream Profile'
        : step === 3 ? 'Media Profile'
        : step === 4 ? 'Existing files'
        : step === 5 ? 'Download Profile'
        : 'Stream Profile'

    return (
        <CollectionExamplesContext.Provider value={examples}>
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
                <ChooseCollectionStep
                    value={collectionInput}
                    onChange={setCollectionInput}
                    onSubmit={(value) => {
                        if (collectionSubmit?.type && collectionSubmit.type !== value.type) {
                            setLocalMediaProfileInput(getZodDefaults(LocalMediaProfileCreateUnionSchema))
                            setLocalMediaProfileSubmit(undefined)
                        }
                        // The download options follow how the show identifies its episodes, and its Source's episode tags.
                        if (collectionSubmit?.episodeIdentifier !== value.episodeIdentifier || collectionTagsKey(collectionSubmit) !== collectionTagsKey(value)) {
                            const tags = qc.getQueryData<EpisodeTagRead[]>(['episodeTags', value.sourceKey, value.sharingUrl])
                            setDownloadProfileInput(defaultDownloadProfile(value.episodeIdentifier, tags))
                            // The starting filters follow once the show's seasons are known too.
                            tagDefaultsAppliedFor.current = undefined
                            setDownloadProfileSubmit(undefined)
                            downloadProfileSubmitRef.current = undefined
                        }
                        setCollectionSubmit(value)
                    }}
                    onSeasonsSubmit={setSeasonsSubmit}
                    onContinue={() => setStep(2)}
                    onCancel={handleCancel}
                />
            )}

            {step === 2 && (
                <CollectionActionStep
                    value={collectionAction}
                    canStreamFromSource={!collectionSubmit || sourceHas(sources.get(collectionSubmit.sourceKey), SourceFeature.RSS_STREAMING)}
                    onChange={setCollectionAction}
                    onBack={() => setStep(1)}
                    onContinue={handleActionContinue}
                    onCancel={handleCancel}
                    isSubmitting={isFinishing}
                />
            )}

            {step === 3 && collectionAction === 'stream' && (
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
                    collectionSlug={collectionSubmit?.slug}
                    collection={collectionSubmit}
                    collectionTitle={collectionSubmit?.title}
                    downloadProfileDefaults={[]}
                    episodeTypesManuallyChanged={streamEpisodeTypesManuallyChanged}
                    onEpisodeTypesManuallyChanged={() => setStreamEpisodeTypesManuallyChanged(true)}
                />
            )}

            {step === 3 && collectionSubmit && (collectionAction === 'download' || collectionAction === 'download-stream') && (
                <LocalMediaProfileStep
                    value={localMediaProfileInput}
                    onChange={setLocalMediaProfileInput}
                    onSubmit={(value) => {
                        setLocalMediaProfileSubmit(value)
                        if (collectionAction === 'download-stream') {
                            setStreamProfileInput((current) => ({
                                ...current,
                                preferredFormat: value.preferredFormat,
                            }))
                        }
                    }}
                    onBack={() => setStep(2)}
                    onContinue={() => {
                        setExistingFiles((current) => current.folder ? current : {
                            ...current,
                            folder: defaultExistingFilesFolder((localMediaProfileSubmit as {outputTemplate?: string} | undefined)?.outputTemplate),
                        })
                        setStep(4)
                    }}
                    onCancel={handleCancel}
                    collectionSlug={collectionSubmit.slug}
                    collection={collectionSubmit}
                    collectionType={collectionSubmit.type}
                />
            )}

            {step === 4 && (collectionAction === 'download' || collectionAction === 'download-stream') && (
                <ExistingFilesStep
                    value={existingFiles}
                    onChange={setExistingFiles}
                    onBack={() => setStep(3)}
                    onContinue={() => setStep(5)}
                    onCancel={handleCancel}
                />
            )}

            {step === 5 && (collectionAction === 'download' || collectionAction === 'download-stream') && (
                <DownloadProfileStep
                    value={downloadProfileInput}
                    onChange={setDownloadProfileInput}
                    onSubmit={(value) => {
                        setDownloadProfileSubmit(value)
                        downloadProfileSubmitRef.current = value
                    }}
                    onBack={() => setStep(4)}
                    onContinue={() => {
                        if (collectionAction === 'download') {
                            void handleFinish('download')
                            return
                        }
                        setStep(6)
                    }}
                    onCancel={handleCancel}
                    collection={collectionSubmit}
                    seasons={seasonsSubmit ?? []}
                    continueLabel={collectionAction === 'download' ? 'Save collection' : 'Continue'}
                />
            )}

            {step === 6 && collectionAction === 'download-stream' && (
                <StreamProfileStep
                    value={streamProfileInput}
                    onChange={setStreamProfileInput}
                    onSubmit={(value) => {
                        setStreamProfileSubmit(value)
                        streamProfileSubmitRef.current = value
                    }}
                    onBack={() => setStep(5)}
                    onFinish={() => handleFinish('download-stream')}
                    onCancel={handleCancel}
                    collectionSlug={collectionSubmit?.slug}
                    collection={collectionSubmit}
                    collectionTitle={collectionSubmit?.title}
                    downloadProfileDefaults={wizardDownloadProfileDefaults}
                    episodeTypesManuallyChanged={streamEpisodeTypesManuallyChanged}
                    onEpisodeTypesManuallyChanged={() => setStreamEpisodeTypesManuallyChanged(true)}
                />
            )}
        </div>
        </CollectionExamplesContext.Provider>
    )
}
