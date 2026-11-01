import {FormEvent, useEffect, useMemo, useRef, useState} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {useQueryClient} from '@tanstack/react-query'
import {useSearchParams} from 'react-router-dom'
import {toast} from 'react-hot-toast'
import {faIcon} from '../icons/faIcon'

import {toImageUrl} from '../components/Episode/EpisodeCard'
import SourceBadge from '../components/Source/SourceBadge'
import {ClearInputButton} from '../components/common/ClearInputButton'
import {useOperations} from '../components/OperationNotifier/OperationNotifier'
import QuickOptionList from '../components/QuickDownload/QuickOptionList'
import QuickFormatPanel from '../components/QuickDownload/QuickFormatPanel'
import {QuickHistoryList, QuickInProgressList, QuickReadyList} from '../components/QuickDownload/QuickDownloadLists'
import '../components/QuickDownload/QuickDownload.css'
import {refreshFrontendPuller} from '../lib/puller'
import {
    QUICK_DOWNLOAD_OPERATION_KIND,
    choiceFromHistory,
    choiceFromSettings,
    choiceSize,
    choiceSummary,
    fetchQuickDownloadOptions,
    fetchQuickDownloadPreview,
    fitChoice,
    fitRules,
    quickDownloadSettingsQueryKey,
    quickDownloadsQueryKey,
    ruleProblem,
    rulesFromSettings,
    saveQuickDownloadPreferences,
    settingsFromChoice,
    sizeLabel,
    startQuickDownload,
    useQuickDownloadHistory,
    useQuickDownloadSettings,
    useQuickDownloads,
    type QuickDownloadPreview,
} from '../lib/quickDownloads'
import {saveSettingsRequest, useSettings} from '../lib/settings'
import {can, getAccess} from '../lib/access'
import type {QuickChoice, QuickDownloadHistoryEntry, QuickDownloadOptions} from '../types/schemas/quick_download'
import type {SettingsFieldPath} from '../types/schemas/settings'
import type {SourceRead} from '../types/schemas/source'

const ACTIVE = new Set(['QUEUED', 'RUNNING', 'WAITING'])

function duration(seconds: number | null | undefined): string | null {
    if (!seconds) return null
    const total = Math.round(seconds)
    const h = Math.floor(total / 3600)
    const m = Math.floor((total % 3600) / 60)
    const s = String(total % 60).padStart(2, '0')
    return h ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`
}

export default function QuickDownloadPage() {
    const [params] = useSearchParams()
    const queryClient = useQueryClient()
    const {data: quickSettings} = useQuickDownloadSettings()
    // With user accounts, everyone saves their own defaults to their account, unless the
    // install locks everyone to its defaults. Without accounts there is one set of defaults,
    // in Settings, so only those who manage Settings may change it from here.
    const ownDefaults = getAccess()?.user != null
    const mayChangeDefaults = ownDefaults ? quickSettings?.lockToDefaults === false : can('settings', 'manage')
    const {data: settings} = useSettings(!ownDefaults && mayChangeDefaults)
    const {operations} = useOperations()
    const {data: quickDownloads} = useQuickDownloads()
    const keepHistory = quickSettings?.keepHistory ?? false
    const {data: history} = useQuickDownloadHistory(keepHistory)
    const defaults = useMemo(() => choiceFromSettings(quickSettings), [quickSettings])
    const rules = useMemo(() => rulesFromSettings(quickSettings), [quickSettings])

    const [url, setUrl] = useState(params.get('url') ?? '')
    const [options, setOptions] = useState<QuickDownloadOptions | null>(null)
    const [error, setError] = useState<string | null>(null)
    const [resolving, setResolving] = useState(false)
    const [preview, setPreview] = useState<QuickDownloadPreview | null>(null)
    const [lookupStarted, setLookupStarted] = useState(0)
    const [candidates, setCandidates] = useState<SourceRead[]>([])
    const [askedSource, setAskedSource] = useState<string | null>(null)
    const [choice, setChoice] = useState<QuickChoice>(defaults)
    const [initialChoice, setInitialChoice] = useState<QuickChoice>(defaults)
    const [panelOpen, setPanelOpen] = useState(false)
    const [saveAsDefaults, setSaveAsDefaults] = useState(false)
    const [starting, setStarting] = useState(false)
    const requestRef = useRef<AbortController | null>(null)
    const inputRef = useRef<HTMLInputElement>(null)

    const lookUp = async (value: string, sourceKey?: string, wanted?: QuickChoice) => {
        const trimmed = value.trim()
        if (!trimmed) return
        if (!sourceKey) setCandidates([])
        setAskedSource(sourceKey ?? null)
        requestRef.current?.abort()
        const controller = new AbortController()
        requestRef.current = controller
        setResolving(true)
        setError(null)
        setOptions(null)
        setPreview(null)
        setLookupStarted(Date.now())
        // The title and thumbnail come back well before the formats; show them as soon as they do.
        void fetchQuickDownloadPreview(trimmed, controller.signal, sourceKey).then((found) => {
            if (!controller.signal.aborted) setPreview(found)
        })
        try {
            const found = await fetchQuickDownloadOptions(trimmed, controller.signal, sourceKey)
            if (controller.signal.aborted) return
            setOptions(found)
            if (found.link.candidates.length) setCandidates(found.link.candidates)
            const fitted = fitRules(fitChoice(wanted ?? defaults, found), found, rules)
            setChoice(fitted)
            setInitialChoice(fitted)
        } catch (exc) {
            if (!controller.signal.aborted) setError(exc instanceof Error ? exc.message : String(exc))
        } finally {
            if (!controller.signal.aborted) setResolving(false)
        }
    }

    useEffect(() => {
        const initial = params.get('url')
        if (initial) void lookUp(initial, params.get('source') ?? undefined)
        return () => requestRef.current?.abort()
        // Only look up the link the page was opened with, once the defaults are known.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [quickSettings !== undefined])

    const clear = () => {
        requestRef.current?.abort()
        setUrl('')
        setOptions(null)
        setError(null)
        setCandidates([])
        setAskedSource(null)
        setResolving(false)
        setPreview(null)
        setPanelOpen(false)
        inputRef.current?.focus()
    }

    const downloadAgain = (entry: QuickDownloadHistoryEntry) => {
        setUrl(entry.url)
        window.scrollTo({top: 0, behavior: 'smooth'})
        void lookUp(entry.url, entry.sourceKey, choiceFromHistory(entry.choice, defaults))
    }

    const submit = (event: FormEvent) => {
        event.preventDefault()
        void lookUp(url)
    }

    const saveDefaults = async () => {
        if (ownDefaults) {
            queryClient.setQueryData(quickDownloadSettingsQueryKey, await saveQuickDownloadPreferences(choice))
            return
        }
        if (!settings) return
        const changes = settingsFromChoice(choice)
        const changedFields = Object.keys(changes).map((key) => `quickDownload.${key}`) as SettingsFieldPath[]
        const values = {...settings.values, quickDownload: {...settings.values.quickDownload, ...changes}}
        const response = await saveSettingsRequest({values, changedFields})
        if (!response.ok) throw new Error('VODLoft could not save your defaults')
        await queryClient.invalidateQueries({queryKey: ['settings']})
        await queryClient.invalidateQueries({queryKey: quickDownloadSettingsQueryKey})
    }

    const forgetOwnDefaults = async () => {
        try {
            const updated = await saveQuickDownloadPreferences(null)
            queryClient.setQueryData(quickDownloadSettingsQueryKey, updated)
            const installDefaults = choiceFromSettings(updated)
            const fitted = options ? fitRules(fitChoice(installDefaults, options), options, rules) : installDefaults
            setChoice(fitted)
            setInitialChoice(fitted)
            setSaveAsDefaults(false)
            toast.success("Back to this VODLoft's defaults.")
        } catch (exc) {
            toast.error(exc instanceof Error ? exc.message : String(exc))
        }
    }

    const download = async () => {
        if (!options) return
        setStarting(true)
        try {
            await startQuickDownload(options.link.url, options.link.source.id, choice)
            if (saveAsDefaults && mayChangeDefaults) {
                try {
                    await saveDefaults()
                    setSaveAsDefaults(false)
                } catch (exc) {
                    toast.error(exc instanceof Error ? exc.message : String(exc))
                }
            }
            await refreshFrontendPuller(queryClient)
            await queryClient.invalidateQueries({queryKey: quickDownloadsQueryKey})
            toast.success(`${options.link.preview.title} is on its way. It shows up under Ready to download.`)
            clear()
        } catch (exc) {
            setError(exc instanceof Error ? exc.message : String(exc))
        } finally {
            setStarting(false)
        }
    }

    const active = operations.filter((operation) => operation.kind === QUICK_DOWNLOAD_OPERATION_KIND && ACTIVE.has(operation.status))
    const ready = quickDownloads?.ready ?? []
    // The history lists what is finished; what is still working or ready to fetch shows above it.
    const shownAbove = new Set([
        ...ready.map((file) => file.id),
        ...active.map((operation) => String(operation.context?.quick_download_id ?? '')),
    ])
    const finished = (history ?? []).filter((entry) => !shownAbove.has(entry.quickDownloadId))
    const link = options?.link
    const image = toImageUrl(link?.preview.imageUrl)
    const size = options ? choiceSize(options, choice) : null
    const summary = choiceSummary(choice)
    const recommended = options ? fitChoice(defaults, options).quality : null
    const problem = options && !options.refused ? ruleProblem(options, choice, rules) : null
    const canDownload = !!options && !options.refused && !problem && !starting

    return (
        <section className="view quick-download-view" aria-labelledby="quick-download-title">
            <div className="view-header">
                <div>
                    <h1 id="quick-download-title">Quick download</h1>
                    <p className="view-description">
                        Paste a link, choose a format, download the file. Nothing is kept: files don't go into your library,
                        and VODLoft deletes each one {quickSettings ? `${quickSettings.keepDownloadedMinutes} minutes` : 'a few minutes'} after you've downloaded it.
                    </p>
                </div>
            </div>

            <div className="quick-download-card">
                <form className="add-media-form" onSubmit={submit}>
                    <label className="sr-only" htmlFor="quick-download-url">Link</label>
                    <span className="add-media-field">
                        <input
                            ref={inputRef}
                            id="quick-download-url"
                            className="input add-media-input"
                            type="text"
                            inputMode="url"
                            autoComplete="off"
                            placeholder="https://…"
                            value={url}
                            onChange={(event) => setUrl(event.target.value)}
                        />
                        {url && <ClearInputButton onClear={clear} label="Clear the link"/>}
                    </span>
                    <button className="btn btn-primary" type="submit" disabled={resolving || !url.trim()}>
                        {resolving ? 'Looking up…' : 'Look up'}
                    </button>
                </form>

                {candidates.length > 1 && (
                    <div className="add-media-sources" role="group" aria-label="Source to look the link up with">
                        <span>Look up with</span>
                        {candidates.map((candidate) => {
                            const current = (link?.source.id ?? askedSource) === candidate.id
                            return (
                                <button key={candidate.id} type="button" className={`btn${current ? ' btn-primary' : ''}`}
                                        aria-pressed={current} disabled={resolving}
                                        onClick={() => { if (!current) void lookUp(url, candidate.id) }}>
                                    {candidate.name}
                                </button>
                            )
                        })}
                    </div>
                )}

                {error && <div className="form-error-card" role="alert">{error}</div>}

                {resolving && !options && <QuickLookupProgress preview={preview} started={lookupStarted}/>}

                {options && link && (
                    <>
                        <article className="quick-preview" aria-label="Link preview">
                            {image && <img src={image} alt="" loading="lazy" decoding="async"/>}
                            <div className="quick-preview-copy">
                                <SourceBadge sourceKey={link.source.id}/>
                                <strong>{link.preview.title}</strong>
                                <small className="quick-muted">
                                    {[link.site, link.preview.authorName, duration(options.duration)].filter(Boolean).join(' · ')}
                                </small>
                            </div>
                        </article>

                        {options.refused ? (
                            <p className="form-error-card" role="alert">{options.refused}</p>
                        ) : (
                            <>
                                <QuickOptionList options={options} choice={choice} recommended={recommended} rules={rules} onChange={setChoice}/>
                                {problem && <p className="form-error-card" role="alert">{problem}</p>}
                                {rules.locked ? (
                                    <span className="quick-muted quick-locked-note">
                                        <FontAwesomeIcon icon={faIcon('fass', 'lock')}/> <span>Set in Settings › Quick download</span>
                                    </span>
                                ) : (
                                    <button type="button" className="quick-link-button" onClick={() => setPanelOpen(true)}>
                                        <FontAwesomeIcon icon={faIcon('fass', 'sliders')}/>
                                        <span>Format and codec</span>
                                    </button>
                                )}
                                <div className="quick-download-footer">
                                    <span className="quick-footer-choice" aria-hidden="true">
                                        <strong>{summary}</strong>
                                        <small>{sizeLabel(size) || 'size unknown'}</small>
                                    </span>
                                    <button type="button" className="btn btn-primary quick-download-button" disabled={!canDownload}
                                            onClick={() => void download()}>
                                        <FontAwesomeIcon icon={faIcon('fass', starting ? 'spinner' : 'download')} spin={starting}/>
                                        <span className="quick-download-button-long">Download {summary}{size ? ` · ${sizeLabel(size)}` : ''}</span>
                                        <span className="quick-download-button-short">Download</span>
                                    </button>
                                </div>
                            </>
                        )}
                    </>
                )}
            </div>

            <QuickInProgressList operations={active}/>
            <QuickReadyList ready={ready}/>
            {keepHistory && <QuickHistoryList entries={finished} onDownloadAgain={downloadAgain}/>}

            {options && !rules.locked && (
                <QuickFormatPanel
                    open={panelOpen}
                    options={options}
                    sourceName={options.link.source.name}
                    choice={choice}
                    initial={initialChoice}
                    rules={rules}
                    saveAsDefaults={saveAsDefaults}
                    onChange={setChoice}
                    onSaveAsDefaultsChange={mayChangeDefaults ? setSaveAsDefaults : undefined}
                    onForgetOwnDefaults={mayChangeDefaults && quickSettings?.ownDefaults ? forgetOwnDefaults : undefined}
                    onClose={() => setPanelOpen(false)}
                />
            )}
        </section>
    )
}

/**
 * While a link is being looked up: its title and thumbnail as soon as they are
 * known, and what VODLoft is still doing, with the time it has taken so far.
 */
function QuickLookupProgress({preview, started}: {preview: QuickDownloadPreview | null; started: number}) {
    const [now, setNow] = useState(() => Date.now())
    useEffect(() => {
        const timer = window.setInterval(() => setNow(Date.now()), 1000)
        return () => window.clearInterval(timer)
    }, [])
    const seconds = Math.max(0, Math.floor((now - started) / 1000))
    const image = toImageUrl(preview?.imageUrl)
    return (
        <div className="quick-lookup" aria-live="polite" aria-busy="true">
            {preview && (
                <article className="quick-preview" aria-label="Link preview">
                    {image && <img src={image} alt="" decoding="async"/>}
                    <div className="quick-preview-copy">
                        <SourceBadge sourceKey={preview.sourceKey}/>
                        <strong>{preview.title}</strong>
                        <small className="quick-muted">{[preview.site, preview.authorName].filter(Boolean).join(' · ')}</small>
                    </div>
                </article>
            )}
            <ol className="quick-lookup-steps">
                <li className={preview ? 'is-done' : 'is-active'}>
                    <FontAwesomeIcon icon={preview ? faIcon('fass', 'check') : faIcon('fass', 'spinner')} spin={!preview}/>
                    <span>{preview ? 'Found the video' : 'Looking up the link'}</span>
                </li>
                <li className={preview ? 'is-active' : ''}>
                    <FontAwesomeIcon icon={preview ? faIcon('fass', 'spinner') : faIcon('fass', 'circle')} spin={!!preview}/>
                    <span>Listing formats and sizes</span>
                    {seconds >= 2 && <small className="quick-muted">{seconds} s</small>}
                </li>
            </ol>
            <div className="quick-lookup-bar" aria-hidden="true"><span/></div>
        </div>
    )
}
