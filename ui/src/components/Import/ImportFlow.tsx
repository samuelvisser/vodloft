import {useEffect, useMemo, useRef, useState, type DragEvent, type ReactNode} from 'react'
import Switch from 'react-switch'
import {useQueryClient} from '@tanstack/react-query'
import toast from 'react-hot-toast'

import FolderField from '../ExistingFiles/FolderField'
import ProgressBar from '../common/ProgressBar'
import {
    IMPORTERS_KEY,
    filesToOffer,
    previewImport,
    readRun,
    removeUpload,
    runReportText,
    startRun,
    uploadFiles,
    uploadFromFolder,
    useImportRuns,
    type UploadProgress,
} from '../../lib/imports'
import type {
    ImportOptions,
    ImportPreview,
    ImportProfile,
    ImportRun,
    ImportRunSummary,
    ImportSupport,
    Importer,
} from '../../types/schemas/imports'

const SUPPORT_LABELS: Record<ImportSupport, string> = {
    exact: 'Exact',
    close: 'Close',
    unsupported: 'Not supported',
}

const DEFAULT_OPTIONS: ImportOptions = {enableDownloadProfiles: false, templates: {}}

function settingLabel(key: string): string {
    const last = key.split('.').slice(-2).join(' › ')
    return last.replace(/_/g, ' ')
}

function formatValue(value: unknown, secret: boolean): string {
    if (secret) return 'Hidden'
    if (value === null || value === undefined) return 'Not set'
    if (typeof value === 'boolean') return value ? 'On' : 'Off'
    if (typeof value === 'object') return JSON.stringify(value)
    return String(value)
}

function download(name: string, text: string) {
    const url = URL.createObjectURL(new Blob([text], {type: 'text/plain'}))
    const link = document.createElement('a')
    link.href = url
    link.download = name
    link.click()
    URL.revokeObjectURL(url)
}

type Props = {
    importer: Importer
    /** Called once a run has finished, so onboarding can move on. */
    onFinished?: (run: ImportRun) => void
}

/** Upload another program's config folder, preview what it brings, then import it. */
export default function ImportFlow({importer, onFinished}: Props) {
    const queryClient = useQueryClient()
    const hasUpload = Boolean(importer.upload.upload)
    const [stage, setStage] = useState<'upload' | 'preview'>(hasUpload ? 'preview' : 'upload')

    const refresh = () => queryClient.invalidateQueries({queryKey: IMPORTERS_KEY})

    return (
        <div className="import-flow">
            {stage === 'upload' ? (
                <UploadStep
                    importer={importer}
                    onUploaded={async () => {
                        await refresh()
                        setStage('preview')
                    }}
                />
            ) : (
                <PreviewStep
                    importer={importer}
                    onReplace={async () => {
                        await removeUpload(importer.key).catch(() => null)
                        await refresh()
                        setStage('upload')
                    }}
                    onFinished={onFinished}
                />
            )}
        </div>
    )
}

function UploadStep({importer, onUploaded}: {importer: Importer, onUploaded: () => Promise<void>}) {
    const [includeSecrets, setIncludeSecrets] = useState(false)
    const [progress, setProgress] = useState<UploadProgress | null>(null)
    const [busy, setBusy] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [skipped, setSkipped] = useState<string[]>([])
    const [folder, setFolder] = useState('')
    const [dragging, setDragging] = useState(false)
    const folderInput = useRef<HTMLInputElement>(null)
    const archiveInput = useRef<HTMLInputElement>(null)
    const abort = useRef<AbortController | null>(null)

    useEffect(() => {
        folderInput.current?.setAttribute('webkitdirectory', '')
        return () => abort.current?.abort()
    }, [])

    async function send(picked: File[]) {
        const files = filesToOffer(picked, importer.files)
        if (!files.length) {
            setError(`These files are not a ${importer.name} config folder: ${importer.files[0]} is missing`)
            return
        }
        setBusy(true)
        setError(null)
        abort.current = new AbortController()
        try {
            const status = await uploadFiles(importer.key, files, includeSecrets, setProgress, abort.current.signal)
            setSkipped(status.skipped)
            await onUploaded()
        } catch (exc) {
            setError(exc instanceof Error ? exc.message : 'The upload failed')
        } finally {
            setBusy(false)
            setProgress(null)
        }
    }

    async function takeFolder() {
        setBusy(true)
        setError(null)
        try {
            await uploadFromFolder(importer.key, folder, includeSecrets)
            await onUploaded()
        } catch (exc) {
            setError(exc instanceof Error ? exc.message : 'VODLoft could not read that folder')
        } finally {
            setBusy(false)
        }
    }

    function onDrop(event: DragEvent) {
        event.preventDefault()
        setDragging(false)
        const files = Array.from(event.dataTransfer.files)
        if (files.length) void send(files)
    }

    return (
        <div className="import-step">
            <p className="import-help">
                Pick {importer.name}'s config folder, or drop an archive of it. VODLoft only takes{' '}
                {importer.files.filter((file) => !importer.secretFiles.includes(file)).map((file) => <code key={file}>{file}</code>)
                    .reduce<ReactNode[]>((all, item, index) => index ? [...all, ', ', item] : [item], [])}
                {' '}and leaves the rest on your computer.
            </p>

            {importer.secretFiles.length > 0 && (
                <div className="settings-field settings-toggle-field settings-field--wide">
                    <div className="settings-toggle-field__control">
                        <div>
                            <label htmlFor={`import-secrets-${importer.key}`}>Also bring sign-ins</label>
                            <div className="settings-field__help">
                                Takes {importer.secretFiles.map((file) => <code key={file}>{file}</code>)} as well, so you
                                stay signed in. VODLoft stores them like its own sign-ins.
                            </div>
                        </div>
                        <Switch
                            id={`import-secrets-${importer.key}`}
                            checked={includeSecrets}
                            disabled={busy}
                            onChange={setIncludeSecrets}
                        />
                    </div>
                </div>
            )}

            <div
                className={`import-drop${dragging ? ' is-dragging' : ''}`}
                onDragOver={(event) => {
                    event.preventDefault()
                    setDragging(true)
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={onDrop}
            >
                <input
                    ref={folderInput}
                    type="file"
                    multiple
                    hidden
                    onChange={(event) => {
                        const files = Array.from(event.target.files ?? [])
                        event.target.value = ''
                        if (files.length) void send(files)
                    }}
                />
                <input
                    ref={archiveInput}
                    type="file"
                    accept=".zip,.tar,.tar.gz,.tgz"
                    hidden
                    onChange={(event) => {
                        const files = Array.from(event.target.files ?? [])
                        event.target.value = ''
                        if (files.length) void send(files)
                    }}
                />
                <div className="import-drop__actions">
                    <button type="button" className="btn btn-primary" disabled={busy} onClick={() => folderInput.current?.click()}>
                        Choose the config folder
                    </button>
                    <button type="button" className="btn" disabled={busy} onClick={() => archiveInput.current?.click()}>
                        Choose an archive
                    </button>
                </div>
                <small>or drop an archive here</small>
            </div>

            {progress && (
                <div className="import-progress" role="status">
                    <span>Sending {progress.file}</span>
                    <ProgressBar ariaLabel="Import progress" value={progress.total ? Math.round(100 * progress.sent / progress.total) : 100}/>
                </div>
            )}

            <details className="import-folder">
                <summary>Use a folder VODLoft can already see</summary>
                <div className="import-folder__body">
                    <p className="settings-field__help">
                        If {importer.name}'s config folder is mounted into VODLoft, pick it here instead of uploading it.
                    </p>
                    <FolderField label="Config folder" value={folder} onChange={setFolder} disabled={busy}/>
                    <button type="button" className="btn" disabled={busy || !folder} onClick={() => void takeFolder()}>
                        Use this folder
                    </button>
                </div>
            </details>

            {skipped.length > 0 && <p className="settings-field__help">Left out: {skipped.join(', ')}</p>}
            {error && <p className="form-error-card" role="alert">{error}</p>}
        </div>
    )
}

function PreviewStep({importer, onReplace, onFinished}: {
    importer: Importer
    onReplace: () => Promise<void>
    onFinished?: (run: ImportRun) => void
}) {
    const queryClient = useQueryClient()
    const [options, setOptions] = useState<ImportOptions>(DEFAULT_OPTIONS)
    const [preview, setPreview] = useState<ImportPreview | null>(null)
    const [error, setError] = useState<string | null>(null)
    const [loading, setLoading] = useState(false)
    const [pathMap, setPathMap] = useState<[string, string]>(['', ''])
    const [run, setRun] = useState<ImportRun | null>(null)
    const [starting, setStarting] = useState(false)

    async function load(next: ImportOptions) {
        setLoading(true)
        setError(null)
        try {
            const result = await previewImport(importer.key, next)
            setPreview(result)
            setPathMap([result.pathMap.source, result.pathMap.target])
            setOptions((current) => ({
                ...next,
                // The first preview decides which settings start ticked.
                settings: current.settings ?? next.settings ?? result.settings.filter((item) => item.selected).map((item) => item.key),
            }))
        } catch (exc) {
            setError(exc instanceof Error ? exc.message : 'The preview failed')
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => {
        void load(DEFAULT_OPTIONS)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [importer.key])

    useEffect(() => {
        if (!run || run.status === 'finished' || run.status === 'failed') return
        const timer = window.setTimeout(async () => {
            try {
                setRun(await readRun(importer.key, run.id))
            } catch {
                // The next poll tries again.
                setRun({...run})
            }
        }, 2000)
        return () => window.clearTimeout(timer)
    }, [importer.key, run])

    useEffect(() => {
        if (run?.status !== 'finished' && run?.status !== 'failed') return
        void queryClient.invalidateQueries({queryKey: ['importRuns', importer.key]})
        void queryClient.invalidateQueries({queryKey: IMPORTERS_KEY})
        if (run.status === 'finished') {
            void queryClient.invalidateQueries({queryKey: ['collections']})
            void queryClient.invalidateQueries({queryKey: ['localMediaProfiles']})
            onFinished?.(run)
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [run?.status])

    async function begin() {
        setStarting(true)
        try {
            const summary = await startRun(importer.key, options)
            setRun(await readRun(importer.key, summary.id))
        } catch (exc) {
            toast.error(exc instanceof Error ? exc.message : 'The import could not start')
        } finally {
            setStarting(false)
        }
    }

    const collections = useMemo(() => {
        if (!preview) return []
        if (preview.records) {
            return preview.records.collections.map((item) => ({
                id: item.externalId, title: item.title ?? item.externalId, becomes: item.becomes, detail: null as string | null,
            }))
        }
        return preview.collections.map((item) => ({
            id: item.externalId,
            title: item.title,
            becomes: item.becomes,
            detail: `${item.filesOnDisk} of ${item.files} files found${item.profileName ? ` · ${item.profileName}` : ''}`,
        }))
    }, [preview])

    if (run) return <RunView importer={importer} run={run} onBack={() => setRun(null)}/>
    if (!preview) {
        return (
            <div className="import-step">
                {loading && <p role="status">Reading the upload…</p>}
                {error && (
                    <>
                        <p className="form-error-card" role="alert">{error}</p>
                        <button type="button" className="btn" onClick={() => void onReplace()}>Upload again</button>
                    </>
                )}
            </div>
        )
    }

    const chosen = new Set(options.collections ?? collections.map((item) => item.id))
    const chosenSettings = new Set(options.settings ?? [])
    const toggleCollection = (id: string, on: boolean) => {
        const next = new Set(chosen)
        if (on) next.add(id)
        else next.delete(id)
        setOptions({...options, collections: collections.map((item) => item.id).filter((item) => next.has(item))})
    }

    return (
        <div className="import-step import-preview" aria-busy={loading}>
            <div className="import-preview__header">
                <div>
                    <strong>{importer.name}{preview.version ? ` ${preview.version}` : ''}</strong>
                    <small>
                        {preview.counts.collections} collection{preview.counts.collections === 1 ? '' : 's'},{' '}
                        {preview.counts.files} file{preview.counts.files === 1 ? '' : 's'}
                    </small>
                </div>
                <button type="button" className="btn" onClick={() => void onReplace()}>Upload again</button>
            </div>

            {preview.warnings.length > 0 && (
                <ul className="import-warnings">
                    {preview.warnings.map((warning, index) => (
                        <li key={index} className={`is-${warning.support}`}><strong>{warning.subject}</strong> {warning.message}</li>
                    ))}
                </ul>
            )}

            <section className="import-block">
                <h3>Where the files are</h3>
                <p className="settings-field__help">
                    {importer.name} saved files under the first folder; VODLoft sees the same files under the second.
                    {preview.pathMap.sampled > 0 && ` ${preview.pathMap.found} of ${preview.pathMap.sampled} sampled files were found.`}
                </p>
                <div className="import-path-map">
                    <input aria-label={`${importer.name} folder`} value={pathMap[0]} onChange={(event) => setPathMap([event.target.value, pathMap[1]])}/>
                    <span aria-hidden="true">→</span>
                    <input aria-label="VODLoft folder" value={pathMap[1]} onChange={(event) => setPathMap([pathMap[0], event.target.value])}/>
                    <button
                        type="button"
                        className="btn"
                        disabled={loading || (pathMap[0] === preview.pathMap.source && pathMap[1] === preview.pathMap.target)}
                        onClick={() => void load({...options, pathMap})}
                    >
                        Check again
                    </button>
                </div>
            </section>

            {collections.length > 0 && (
                <section className="import-block">
                    <h3>Collections</h3>
                    <ul className="import-checklist">
                        {collections.map((item) => (
                            <li key={item.id}>
                                <label>
                                    <input type="checkbox" checked={chosen.has(item.id)} onChange={(event) => toggleCollection(item.id, event.target.checked)}/>
                                    <span>{item.title}</span>
                                </label>
                                <small>
                                    {item.becomes === 'new' ? 'New' : item.becomes === 'linked' ? 'Joins the one in your library' : 'Already imported'}
                                    {item.detail ? ` · ${item.detail}` : ''}
                                </small>
                            </li>
                        ))}
                    </ul>
                </section>
            )}

            {preview.profiles.length > 0 && (
                <section className="import-block">
                    <h3>Local Media Profiles</h3>
                    {preview.profiles.map((profile) => (
                        <ProfilePreview
                            key={profile.externalId}
                            profile={profile}
                            template={options.templates[profile.externalId]}
                            onTemplate={(template) => {
                                const templates = {...options.templates}
                                if (template === null) delete templates[profile.externalId]
                                else templates[profile.externalId] = template
                                const next = {...options, templates}
                                setOptions(next)
                                void load(next)
                            }}
                        />
                    ))}
                </section>
            )}

            {preview.settings.length > 0 && (
                <section className="import-block">
                    <h3>Settings</h3>
                    <ul className="import-checklist">
                        {preview.settings.map((setting) => (
                            <li key={setting.key}>
                                <label>
                                    <input
                                        type="checkbox"
                                        disabled={setting.support === 'unsupported'}
                                        checked={chosenSettings.has(setting.key)}
                                        onChange={(event) => {
                                            const next = new Set(chosenSettings)
                                            if (event.target.checked) next.add(setting.key)
                                            else next.delete(setting.key)
                                            setOptions({...options, settings: [...next]})
                                        }}
                                    />
                                    <span>{settingLabel(setting.key)}</span>
                                </label>
                                <small>
                                    {formatValue(setting.value, setting.secret)}
                                    {setting.support !== 'exact' ? ` · ${SUPPORT_LABELS[setting.support]}` : ''}
                                    {setting.note ? ` · ${setting.note}` : ''}
                                </small>
                            </li>
                        ))}
                    </ul>
                </section>
            )}

            <div className="settings-field settings-toggle-field settings-field--wide">
                <div className="settings-toggle-field__control">
                    <div>
                        <label htmlFor={`import-enable-${importer.key}`}>Turn on Download Profiles</label>
                        <div className="settings-field__help">
                            Imported Download Profiles start off, so nothing downloads before you have looked.
                            Turn this on to keep downloading where {importer.name} left off.
                        </div>
                    </div>
                    <Switch
                        id={`import-enable-${importer.key}`}
                        checked={options.enableDownloadProfiles}
                        onChange={(on) => setOptions({...options, enableDownloadProfiles: on})}
                    />
                </div>
            </div>

            {error && <p className="form-error-card" role="alert">{error}</p>}

            <div className="import-actions">
                <button type="button" className="btn btn-primary" disabled={starting || loading || chosen.size === 0 && collections.length > 0} onClick={() => void begin()}>
                    {starting ? 'Starting…' : 'Import'}
                </button>
            </div>

            <RunHistory importer={importer} onOpen={async (id) => setRun(await readRun(importer.key, id))}/>
        </div>
    )
}

function ProfilePreview({profile, template, onTemplate}: {
    profile: ImportProfile
    template: string | undefined
    onTemplate: (template: string | null) => void
}) {
    const [editing, setEditing] = useState(false)
    const [draft, setDraft] = useState(template ?? profile.outputTemplate ?? '')
    const proof = profile.pathProof

    return (
        <div className={`import-profile is-${profile.support}`}>
            <div className="import-profile__title">
                <strong>{profile.name}</strong>
                <small>
                    {profile.becomes === 'new' ? 'New profile' : `Uses ${profile.localMediaProfileName ?? 'an existing profile'}`}
                    {' · '}{SUPPORT_LABELS[profile.support]}
                </small>
            </div>
            {editing ? (
                <div className="import-template-editor">
                    <textarea aria-label={`${profile.name} output template`} rows={3} value={draft} onChange={(event) => setDraft(event.target.value)}/>
                    <div className="import-actions">
                        <button type="button" className="btn" onClick={() => setEditing(false)}>Cancel</button>
                        {template !== undefined && (
                            <button type="button" className="btn" onClick={() => {
                                onTemplate(null)
                                setEditing(false)
                            }}>Use the converted template</button>
                        )}
                        <button type="button" className="btn btn-primary" onClick={() => {
                            onTemplate(draft)
                            setEditing(false)
                        }}>Check this template</button>
                    </div>
                </div>
            ) : (
                <div className="import-template">
                    <code>{profile.outputTemplate ?? 'No template'}</code>
                    <button type="button" className="btn" onClick={() => {
                        setDraft(template ?? profile.outputTemplate ?? '')
                        setEditing(true)
                    }}>Edit</button>
                </div>
            )}
            <p className={`import-proof${proof.error || proof.differences.length ? ' is-different' : ''}`}>
                {proof.error
                    ? proof.error
                    : proof.total === 0
                        ? 'No files to compare yet.'
                        : `${proof.identical} of ${proof.total} existing files get the same path in VODLoft.`}
            </p>
            {proof.differences.length > 0 && (
                <ul className="import-differences">
                    {proof.differences.slice(0, 5).map((item) => (
                        <li key={item.path}><code>{item.path}</code><code>{item.rendered}</code></li>
                    ))}
                </ul>
            )}
            {[...profile.report, ...profile.warnings.map((warning) => warning.message)].length > 0 && (
                <ul className="import-notes">
                    {profile.report.map((line, index) => <li key={`r${index}`}>{line}</li>)}
                    {profile.warnings.map((warning, index) => <li key={`w${index}`}>{warning.message}</li>)}
                </ul>
            )}
        </div>
    )
}

const RUN_LABELS: Record<ImportRunSummary['status'], string> = {
    running: 'Running',
    waiting: 'Waiting for indexing',
    finished: 'Finished',
    failed: 'Failed',
}

function countsLine(counts: Record<string, number>): string {
    return Object.entries(counts).filter(([, value]) => value).map(([key, value]) => `${value} ${key.replace(/_/g, ' ')}`).join(', ')
}

function RunView({importer, run, onBack}: {importer: Importer, run: ImportRun, onBack: () => void}) {
    const done = run.status === 'finished' || run.status === 'failed'
    return (
        <div className="import-step import-run" aria-live="polite">
            <div className="import-preview__header">
                <div>
                    <strong>Import #{run.id}: {RUN_LABELS[run.status]}</strong>
                    <small>{countsLine(run.counts) || 'Nothing counted yet'}</small>
                </div>
                <div className="import-actions">
                    <button type="button" className="btn" onClick={() => download(`${importer.key}-import-${run.id}.txt`, runReportText(importer.name, run))}>
                        Download report
                    </button>
                    {done && <button type="button" className="btn" onClick={onBack}>Back</button>}
                </div>
            </div>
            {!done && <ProgressBar ariaLabel="Import progress" value={run.steps.length ? Math.round(100 * run.steps.filter((step) => step.status !== 'waiting').length / run.steps.length) : 0}/>}
            {run.error && <p className="form-error-card" role="alert">{run.error}</p>}
            {run.steps.length > 0 && (
                <ul className="import-checklist">
                    {run.steps.map((step, index) => (
                        <li key={index} className={`is-${step.status}`}>
                            <span>{step.collectionTitle ?? step.collectionSlug}</span>
                            <small>
                                {step.status === 'waiting' ? 'Waiting for indexing' : step.status === 'failed' ? 'Failed' : countsLine(step.counts) || 'Done'}
                                {step.problems.length ? ` · ${step.problems.length} problem${step.problems.length === 1 ? '' : 's'}` : ''}
                            </small>
                        </li>
                    ))}
                </ul>
            )}
            {run.report.length > 0 && (
                <ul className="import-notes">
                    {run.report.slice(0, 50).map((entry, index) => (
                        <li key={index}><strong>{entry.subject}</strong> {entry.message}</li>
                    ))}
                    {run.report.length > 50 && <li>…and {run.report.length - 50} more in the report</li>}
                </ul>
            )}
        </div>
    )
}

function RunHistory({importer, onOpen}: {importer: Importer, onOpen: (id: number) => void}) {
    const runs = useImportRuns(importer.key)
    if (!runs.data?.length) return null
    return (
        <section className="import-block">
            <h3>Earlier imports</h3>
            <ul className="import-checklist">
                {runs.data.map((run) => (
                    <li key={run.id}>
                        <button type="button" className="import-link" onClick={() => onOpen(run.id)}>
                            #{run.id} · {new Date(run.createdAt).toLocaleString()}
                        </button>
                        <small>{RUN_LABELS[run.status]}{countsLine(run.counts) ? ` · ${countsLine(run.counts)}` : ''}</small>
                    </li>
                ))}
            </ul>
        </section>
    )
}
