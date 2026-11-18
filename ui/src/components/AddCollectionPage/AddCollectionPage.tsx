import {useEffect, useMemo, useRef, useState} from 'react'
import {getErrorMessageFromResponse} from '../../utils/helpers'
import {clearFormDraft, loadFormDraft, saveFormDraft} from '../FormDraft/formDraft'
import UnsavedChangesBar from '../FormDraft/UnsavedChangesBar'
import ChooseCollectionStep from './ChooseCollectionStep'
import CollectionActionStep, {CollectionAction} from './CollectionActionStep'
import LocalMediaProfileStep from './LocalMediaProfileStep'
import DownloadProfileStep from './DownloadProfileStep'
import StreamProfileStep from './StreamProfileStep'
import {defaultExistingFilesFolder, type ExistingFilesChoice} from './ExistingFilesFields'
import {layoutTemplate} from '../ExistingFiles/ExistingFilesSetup'

import {CollectionCreatePayloadOut, CollectionRead, CollectionCreatePayloadIn, CollectionCreatePayloadSchema} from "../../types/schemas/collection";
import {getZodDefaults} from "../../utils/defaultZod";
import {
    DownloadProfileBundleSchema, DownloadProfileBundleIn, DownloadProfileBundleOut,
    LocalMediaProfileChoiceIn,
    LocalMediaProfileChoiceOut,
    LocalMediaProfileCreateUnionSchema,
    RssStreamProfileBundleIn,
    RssStreamProfileBundleOut,
    RssStreamProfileBundleSchema,
} from "../../types/schemas/collection_as_bundle";
import {defaultEpisodeFilters} from "../../types/schemas/download_profile";
import {downloadedEpisodeTypes} from "../DownloadProfile/episodeFilters";
import {useQueryClient} from "@tanstack/react-query";
import {SeasonDetachedOut} from "../../types/schemas/season";
import {LocalMediaProfileRead} from "../../types/schemas/local_media_profile";
import {PreferredFormatReg} from "../../types/local_media_profile";
import {useEpisodeTags, useLocalMediaProfiles, useSiteOptions} from "../../lib/queries";
import {EpisodeTagRead} from "../../types/schemas/source";
import {CollectionExamplesContext, useCollectionExamplesQuery} from "../../lib/collectionExamples";
import {apiUrl} from '../../lib/api'

export type Props = {
    onCancel: () => void
    // Receives the path of the new collection's page once the collection is saved.
    onCreated: (path: string) => void
    initialUrl?: string
}

const STORAGE_KEY = 'addCollectionWizardV12'

type WizardType = 'ERROR' | 'INFO'
type WizardMessage = { text: string; type: WizardType }
type WizardStep = 1 | 2 | 3 | 4 | 5

type WizardState = {
    step: WizardStep
    action?: CollectionAction
    collection: {
        input: Partial<CollectionCreatePayloadIn>,
        submit: CollectionCreatePayloadOut | undefined,
    },
    localMediaProfile: {
        input: Partial<LocalMediaProfileChoiceIn>,
        submit: LocalMediaProfileChoiceOut | undefined,
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

// The wizard keeps where the user is in this browser, so a reload or a look elsewhere does not lose it.
const DRAFT_SCHEMA_VERSION = 'add-collection-wizard-v12'

const loadWizardState = () => loadFormDraft<WizardState>(STORAGE_KEY, DRAFT_SCHEMA_VERSION)
const saveWizardState = (state: WizardState) => saveFormDraft(STORAGE_KEY, DRAFT_SCHEMA_VERSION, state)
const clearWizardState = () => clearFormDraft(STORAGE_KEY)

/**
 * Whether the saved wizard holds anything the user did, rather than only the first step as it opened: empty, or
 * with the collection link the wizard was opened with.
 */
const hasWizardProgress = (state: WizardState | null, initialUrl?: string) => (
    !!state && (state.step > 1 || (!initialUrl && !!state.collection.input.url?.trim()))
)

/** The settings of the profile the collection gets: the new one, or the existing one it picked. */
function chosenProfileSettings(
    choice: LocalMediaProfileChoiceOut | undefined,
    profiles: LocalMediaProfileRead[] | undefined,
): Pick<LocalMediaProfileRead, 'preferredFormat' | 'outputTemplate'> | undefined {
    if (choice?.op === 'use_existing') return profiles?.find((profile) => profile.slug === choice.slug)
    return choice
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
    ...getZodDefaults(RssStreamProfileBundleSchema),
    useSourceStream: action === 'stream',
    preferredFormat: 'format_1080p',
})

export default function AddCollectionPage(props: Props) {
    // Starting over mounts a fresh wizard, so every step begins from its defaults again.
    const [generation, setGeneration] = useState(0)
    return (
        <AddCollectionWizard
            key={generation}
            {...props}
            onStartOver={() => {
                clearWizardState()
                setGeneration((current) => current + 1)
            }}
        />
    )
}

function AddCollectionWizard({onCancel, onCreated, initialUrl, onStartOver}: Props & {onStartOver: () => void}) {
    // A link that opens the wizard for a collection (?url=...) still finds the wizard as it was left for that
    // collection, so a reload keeps the user's place; for another collection it starts over.
    const [persisted] = useState(() => {
        const saved = loadWizardState()
        if (!initialUrl || saved?.collection.input.url?.trim() === initialUrl.trim()) return saved
        return null
    })
    const [showRestored, setShowRestored] = useState(() => hasWizardProgress(persisted, initialUrl))
    const [globalMessage, setGlobalMessage] = useState<WizardMessage | null>(() => persisted?.globalMessage ?? null)
    const [isFinishing, setIsFinishing] = useState(false)
    const setWizardMessage = (message: string, type: WizardType) => setGlobalMessage({text: message, type})
    const clearWizardMessage = () => setGlobalMessage(null)
    const qc = useQueryClient()

    const [step, setStep] = useState<WizardStep>(() => persisted?.step ?? 1)
    const previousStepRef = useRef(step)
    const [collectionAction, setCollectionAction] = useState<CollectionAction | undefined>(() => persisted?.action)

    const [collectionInput, setCollectionInput] = useState<Partial<CollectionCreatePayloadIn>>(
        () => ({
            ...(persisted?.collection.input ?? getZodDefaults(CollectionCreatePayloadSchema)),
            ...(initialUrl ? {url: initialUrl} : {}),
        }))
    const [collectionSubmit, setCollectionSubmit] = useState<CollectionCreatePayloadOut | undefined>(() => persisted?.collection.submit)

    const [localMediaProfileInput, setLocalMediaProfileInput] = useState<Partial<LocalMediaProfileChoiceIn>>(
        () => persisted?.localMediaProfile.input ?? getZodDefaults(LocalMediaProfileCreateUnionSchema))
    const [localMediaProfileSubmit, setLocalMediaProfileSubmit] = useState<LocalMediaProfileChoiceOut | undefined>(() => persisted?.localMediaProfile.submit)

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
    // Streaming is offered when the collection's Site, such as YouTube, can stream.
    const {data: collectionSite} = useSiteOptions({sourceKey: collectionSubmit?.sourceKey, url: collectionSubmit?.sharingUrl})
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

    const {data: localMediaProfiles} = useLocalMediaProfiles()
    const chosenProfile = chosenProfileSettings(localMediaProfileSubmit, localMediaProfiles)

    const wizardDownloadProfileDefaults = useMemo(() => {
        if (!chosenProfile || !downloadProfileSubmit) return []
        return [{
            preferredFormat: chosenProfile.preferredFormat,
            episodeTypes: downloadedEpisodeTypes(downloadProfileSubmit.filters),
            enabled: downloadProfileSubmit.enableProfile,
        }]
    }, [chosenProfile, downloadProfileSubmit])

    useEffect(() => {
        const previousStep = previousStepRef.current
        previousStepRef.current = step
        // Moving to another step answers the restored notice: the user carries on.
        if (step !== previousStep) setShowRestored(false)
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

        let localMediaProfile: LocalMediaProfileChoiceOut | undefined
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

        let created: CollectionRead
        try {
            const response = await fetch(`${apiUrl()}/collections/as-bundle`, {
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
            created = await response.json() as CollectionRead
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
            qc.invalidateQueries({queryKey: ['streamProfilesView']}),
            qc.invalidateQueries({queryKey: ['collections']}),
            qc.invalidateQueries({queryKey: ['seasons']}),
        ])
        clearWizardState()
        const path = `/collection/${encodeURIComponent(created.slug)}`
        // The scan of existing files waits for the episodes; its review opens on the collection's page.
        onCreated(downloadProfile && existingFiles.enabled ? `${path}?existingFiles=open` : path)
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
                useSourceStream: collectionAction === 'stream',
            }))
        }
        setStep(3)
    }

    // The newest episodes serve as examples in the later steps; they load in the background.
    const examples = useCollectionExamplesQuery(collectionSubmit, seasonsSubmit)

    const totalSteps = collectionAction === 'download-stream' ? 5 : collectionAction === 'download' ? 4 : collectionAction === 'stream' ? 3 : 2
    const stepTitle = step === 1 ? 'Choose collection'
        : step === 2 ? 'Choose what VODLoft should do'
        : collectionAction === 'stream' ? 'Stream Profile'
        : step === 3 ? 'Media Profile'
        : step === 4 ? 'Download Profile'
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
                    canStreamFromSource={!collectionSubmit || (collectionSite ? collectionSite.streamMethods.length > 0 : true)}
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
                        const settings = chosenProfileSettings(value, localMediaProfiles)
                        // The collection root fills the folder in once the example is shown; this covers a profile without one.
                        setExistingFiles((current) => current.folder ? current : {
                            ...current,
                            folder: defaultExistingFilesFolder(settings?.outputTemplate),
                        })
                        const preferredFormat = settings?.preferredFormat
                        if (collectionAction === 'download-stream' && PreferredFormatReg.is(preferredFormat)) {
                            setStreamProfileInput((current) => ({...current, preferredFormat}))
                        }
                    }}
                    onBack={() => setStep(2)}
                    onContinue={() => setStep(4)}
                    onCancel={handleCancel}
                    existingFiles={existingFiles}
                    onExistingFilesChange={setExistingFiles}
                    collectionSlug={collectionSubmit.slug}
                    collection={collectionSubmit}
                    siteKey={collectionSite?.siteKey}
                    collectionType={collectionSubmit.type}
                />
            )}

            {step === 4 && (collectionAction === 'download' || collectionAction === 'download-stream') && (
                <DownloadProfileStep
                    value={downloadProfileInput}
                    onChange={setDownloadProfileInput}
                    onSubmit={(value) => {
                        setDownloadProfileSubmit(value)
                        downloadProfileSubmitRef.current = value
                    }}
                    onBack={() => setStep(3)}
                    onContinue={() => {
                        if (collectionAction === 'download') {
                            void handleFinish('download')
                            return
                        }
                        setStep(5)
                    }}
                    onCancel={handleCancel}
                    collection={collectionSubmit}
                    seasons={seasonsSubmit ?? []}
                    continueLabel={collectionAction === 'download' ? 'Save collection' : 'Continue'}
                />
            )}

            {step === 5 && collectionAction === 'download-stream' && (
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
                    collectionSlug={collectionSubmit?.slug}
                    collection={collectionSubmit}
                    collectionTitle={collectionSubmit?.title}
                    downloadProfileDefaults={wizardDownloadProfileDefaults}
                    episodeTypesManuallyChanged={streamEpisodeTypesManuallyChanged}
                    onEpisodeTypesManuallyChanged={() => setStreamEpisodeTypesManuallyChanged(true)}
                />
            )}
            {showRestored && (
                <UnsavedChangesBar
                    title="Unsaved collection restored"
                    message="The wizard was restored to where you left off in this browser. The collection has not been added yet."
                >
                    <button className="btn" type="button" disabled={isFinishing} onClick={onStartOver}>
                        Start over
                    </button>
                    <button className="btn btn-primary" type="button" onClick={() => setShowRestored(false)}>
                        Dismiss
                    </button>
                </UnsavedChangesBar>
            )}
        </div>
        </CollectionExamplesContext.Provider>
    )
}
