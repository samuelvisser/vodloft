import {useEffect, useId, useMemo, useState} from 'react'
import {useQueryClient} from '@tanstack/react-query'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import toast from 'react-hot-toast'
import {faIcon} from '../../icons/faIcon'
import SimpleSelect from '../common/SimpleSelect'
import {createSelectRegistry} from '../../utils/selectRegistry'
import type {ExistingFile, ExistingFileEpisode, ExistingFilesScan} from '../../types/schemas/existing_files'
import ExistingFilesSetup, {ExistingFilesSetupValue, layoutTemplate} from './ExistingFilesSetup'
import {adoptFiles, finishScan, startScan, useExistingFilesScan} from './api'
import './ExistingFiles.css'

export type ExistingFilesProfile = {id: number, name: string}

type Props = {
    collectionSlug: string
    collectionTitle: string
    profiles: ExistingFilesProfile[]
    initialProfileId?: number
    onClose: () => void
    /** Opens VODLoft's rename for this profile, to give the adopted files the profile's names. */
    onRename?: (localMediaProfileId: number) => void
}

export type Filter = 'certain' | 'likely' | 'review' | 'unmatched' | 'adopted'
export const FILTER_LABELS: Record<Filter, string> = {
    certain: 'Matched for certain',
    likely: 'Likely',
    review: 'Please check',
    unmatched: 'Not matched',
    adopted: 'Adopted',
}
export const SHOWN = 200

export function filterOf(file: ExistingFile): Filter {
    if (file.adopted) return 'adopted'
    return file.confidence ?? 'unmatched'
}

function fileName(path: string, folder?: string | null) {
    const base = (folder ?? '').replace(/\/$/, '')
    return base && path.startsWith(`${base}/`) ? path.slice(base.length + 1) : path
}

export default function ExistingFilesDialog({collectionSlug, collectionTitle, profiles, initialProfileId, onClose, onRename}: Props) {
    const qc = useQueryClient()
    const profileSelectId = useId()
    const [profileId, setProfileId] = useState<number | undefined>(initialProfileId ?? profiles[0]?.id)
    const {data: scan, refetch} = useExistingFilesScan(collectionSlug, profileId)
    const [setup, setSetup] = useState<ExistingFilesSetupValue | null>(null)
    const [editing, setEditing] = useState(false)
    const [busy, setBusy] = useState<string | null>(null)
    const [filter, setFilter] = useState<Filter>('certain')
    const [picks, setPicks] = useState<Record<string, number>>({})
    const [shown, setShown] = useState(SHOWN)

    useEffect(() => {
        if (!scan) return
        setSetup((current) => current ?? {folder: scan.folder ?? scan.defaultFolder, template: ''})
        if (scan.status === 'none') setEditing(true)
    }, [scan])
    useEffect(() => {
        setSetup(null)
        setEditing(false)
        setPicks({})
    }, [profileId])

    const profileRegistry = useMemo(() => createSelectRegistry(
        'ExistingFilesProfile',
        Object.fromEntries(profiles.map((profile) => [String(profile.id), {label: profile.name}])),
        profiles.map((profile) => String(profile.id)),
    ), [profiles])

    const files = scan?.files ?? []
    const counts = scan?.counts
    const visible = files.filter((file) => filterOf(file) === filter)
    const toAdopt = files.filter((file) => !file.adopted && file.episode && (file.confidence === 'certain' || file.confidence === 'likely'))
    const picked = Object.entries(picks)
        .filter(([path]) => files.some((file) => file.path === path && !file.adopted))
        .map(([path, episodeId]) => ({path, episodeId}))

    async function refresh() {
        await Promise.all([
            refetch(),
            qc.invalidateQueries({queryKey: ['existingFilesScans', collectionSlug]}),
            qc.invalidateQueries({queryKey: ['mediaDownloads']}),
            qc.invalidateQueries({queryKey: ['downloadProfilesView']}),
        ])
    }

    async function scanNow() {
        if (!profileId || !setup) return
        setBusy('scan')
        try {
            await startScan(collectionSlug, {
                localMediaProfileId: profileId,
                folder: setup.folder,
                template: layoutTemplate(setup.folder, setup.template),
            })
            setEditing(false)
            setPicks({})
            await refresh()
        } catch (exc) {
            toast.error(exc instanceof Error ? exc.message : 'Could not start the scan')
        } finally {
            setBusy(null)
        }
    }

    async function adopt(matches: {path: string, episodeId: number}[]) {
        if (!profileId || matches.length === 0) return
        setBusy('adopt')
        try {
            const result = await adoptFiles(collectionSlug, profileId, matches)
            if (result.errors.length) {
                toast.error(`${result.errors.length} file(s) were not adopted: ${result.errors[0].error}`)
            }
            toast.success(`Adopted ${result.adopted} file${result.adopted === 1 ? '' : 's'}`)
            setPicks({})
            await refresh()
        } catch (exc) {
            toast.error(exc instanceof Error ? exc.message : 'Could not adopt the files')
        } finally {
            setBusy(null)
        }
    }

    async function finish() {
        if (!profileId) return
        setBusy('finish')
        try {
            const result = await finishScan(collectionSlug, profileId)
            if (result.downloadProfilesEnabled) {
                toast.success('The Download Profile is on and downloads the episodes that have no file yet')
            }
            await refresh()
            onClose()
        } catch (exc) {
            toast.error(exc instanceof Error ? exc.message : 'Could not finish')
        } finally {
            setBusy(null)
        }
    }

    const working = scan?.status === 'waiting' || scan?.status === 'scanning'

    return (
        <div className="modal-overlay" role="presentation">
            <div className="modal existing-files-dialog" role="dialog" aria-modal="true" aria-labelledby={`${profileSelectId}-title`}>
                <div className="modal-header">
                    <div className="modal-icon" aria-hidden><FontAwesomeIcon icon={faIcon('fass', 'file-import')}/></div>
                    <h2 id={`${profileSelectId}-title`} className="modal-title">Match existing files</h2>
                </div>
                <div className="existing-files-body">
                    <p className="existing-files-intro">
                        VODLoft adopts the files it recognises for "{collectionTitle}" and won't download those
                        episodes again.
                    </p>
                    {profiles.length > 1 && (
                        <div className="form-row">
                            <label htmlFor={profileSelectId}>Local Media Profile</label>
                            <SimpleSelect
                                inputId={profileSelectId}
                                registry={profileRegistry}
                                value={profileId ? String(profileId) : null}
                                onChange={(value) => setProfileId(Number(value))}
                                isDisabled={busy !== null}
                            />
                        </div>
                    )}

                    {setup && (editing || scan?.status === 'failed') && (
                        <>
                            {scan?.status === 'failed' && <div className="form-error-card" role="alert">{scan.error}</div>}
                            <ExistingFilesSetup value={setup} onChange={setSetup} disabled={busy !== null}/>
                            <div className="existing-files-actions">
                                <button type="button" className="btn btn-primary" disabled={busy !== null || !setup.folder}
                                        onClick={() => void scanNow()}>
                                    <FontAwesomeIcon icon={faIcon('fass', 'magnifying-glass')} aria-hidden="true"/>
                                    <span>Scan</span>
                                </button>
                            </div>
                        </>
                    )}

                    {working && (
                        <div className="form-info-card" role="status" aria-live="polite">
                            {scan?.status === 'waiting'
                                ? 'Waiting for the episodes to be indexed. The scan starts by itself.'
                                : `Reading ${scan?.folder}…`}
                        </div>
                    )}

                    {scan && counts && !editing && (scan.status === 'ready' || scan.status === 'finished') && (
                        <Results
                            scan={scan}
                            filter={filter}
                            setFilter={(value) => { setFilter(value); setShown(SHOWN) }}
                            visible={visible.slice(0, shown)}
                            more={visible.length - shown}
                            onMore={() => setShown((current) => current + SHOWN)}
                            picks={picks}
                            setPick={(path, episodeId) => setPicks((current) => {
                                const next = {...current}
                                if (episodeId) next[path] = episodeId
                                else delete next[path]
                                return next
                            })}
                        />
                    )}
                </div>

                <div className="modal-actions existing-files-footer">
                    <button type="button" className="btn" onClick={onClose} disabled={busy !== null}>Close</button>
                    {scan && !editing && scan.status !== 'none' && (
                        <button type="button" className="btn" disabled={busy !== null} onClick={() => setEditing(true)}>
                            Scan again
                        </button>
                    )}
                    {scan?.status === 'ready' && picked.length > 0 && (
                        <button type="button" className="btn" disabled={busy !== null} onClick={() => void adopt(picked)}>
                            Adopt {picked.length} checked
                        </button>
                    )}
                    {scan?.status === 'ready' && toAdopt.length > 0 && (
                        <button type="button" className="btn btn-primary" disabled={busy !== null}
                                onClick={() => void adopt(toAdopt.map((file) => ({path: file.path, episodeId: file.episode!.id})))}>
                            {busy === 'adopt' ? 'Adopting…' : `Adopt ${toAdopt.length}`}
                        </button>
                    )}
                    {scan && (counts?.adopted ?? 0) > 0 && onRename && profileId && (
                        <button type="button" className="btn" disabled={busy !== null} onClick={() => onRename(profileId)}>
                            Rename to this profile's template
                        </button>
                    )}
                    {scan?.status === 'ready' && (
                        <button type="button" className={toAdopt.length ? 'btn' : 'btn btn-primary'} disabled={busy !== null}
                                onClick={() => void finish()}>
                            {scan.heldDownloadProfiles > 0 ? 'Done, download the rest' : 'Done'}
                        </button>
                    )}
                </div>
            </div>
        </div>
    )
}

type ResultsProps = {
    scan: Pick<ExistingFilesScan, 'folder' | 'heldDownloadProfiles' | 'episodesWithoutFile'> & {counts?: ExistingFilesScan['counts']}
    /** Name each episode's Collection, for a review of several Collections. */
    showCollection?: boolean
    filter: Filter
    setFilter: (filter: Filter) => void
    visible: ExistingFile[]
    more: number
    onMore: () => void
    picks: Record<string, number>
    setPick: (path: string, episodeId: number | null) => void
}

export function Results({scan, showCollection = false, filter, setFilter, visible, more, onMore, picks, setPick}: ResultsProps) {
    const counts = scan.counts!
    return (
        <div className="existing-files-results">
            <div className="existing-files-counts" role="tablist" aria-label="Matches">
                {(Object.keys(FILTER_LABELS) as Filter[]).map((key) => (
                    <button key={key} type="button" role="tab" aria-selected={filter === key}
                            className={`existing-files-count existing-files-count-${key}${filter === key ? ' active' : ''}`}
                            onClick={() => setFilter(key)}>
                        <strong>{counts[key]}</strong> <span>{FILTER_LABELS[key]}</span>
                    </button>
                ))}
                <div className="existing-files-count existing-files-count-missing">
                    <strong>{scan.episodesWithoutFile}</strong> <span>Episodes with no file</span>
                </div>
            </div>
            {scan.heldDownloadProfiles > 0 && (
                <div className="help">The Download Profile waits until you are done here, then only downloads the episodes without a file.</div>
            )}
            {visible.length === 0 ? (
                <div className="help existing-files-empty">Nothing here.</div>
            ) : (
                <div className="existing-files-table" role="table">
                    <div className="existing-files-row existing-files-head" role="row">
                        <span role="columnheader">File</span>
                        <span role="columnheader">Episode</span>
                        <span role="columnheader">Matched by</span>
                    </div>
                    {visible.map((file) => (
                        <div key={file.path} className="existing-files-row" role="row">
                            <span role="cell" className="existing-files-path" title={file.path}>{fileName(file.path, scan.folder)}</span>
                            <span role="cell">
                                {(filter === 'review' || filter === 'unmatched') ? (
                                    <EpisodePick file={file} showCollection={showCollection} value={picks[file.path]}
                                                 onChange={(id) => setPick(file.path, id)}/>
                                ) : (
                                    file.episode ? <EpisodeLabel episode={file.episode} showCollection={showCollection}/> : 'no match'
                                )}
                                {file.note && <div className="help">{file.note}</div>}
                            </span>
                            <span role="cell">{file.matchedBy ?? 'Not matched'}</span>
                        </div>
                    ))}
                    {more > 0 && (
                        <button type="button" className="btn existing-files-more" onClick={onMore}>Show {Math.min(more, SHOWN)} more</button>
                    )}
                </div>
            )}
        </div>
    )
}

function EpisodeLabel({episode, showCollection}: {episode: ExistingFileEpisode, showCollection: boolean}) {
    return (
        <>
            {episode.title}
            {episode.date && <span className="existing-files-date"> · {episode.date}</span>}
            {showCollection && <span className="existing-files-date"> · {episode.collectionTitle}</span>}
        </>
    )
}

type EpisodePickProps = {file: ExistingFile, showCollection: boolean, value?: number, onChange: (id: number | null) => void}

function EpisodePick({file, showCollection, value, onChange}: EpisodePickProps) {
    const options = [...(file.episode ? [file.episode] : []), ...file.candidates]
        .filter((episode, index, all) => all.findIndex((other) => other.id === episode.id) === index)
    const registry = useMemo(() => createSelectRegistry(
        'ExistingFileEpisode',
        {
            '': {label: "Don't adopt"},
            ...Object.fromEntries(options.map((episode) => [
                String(episode.id), {label: `${episode.title}${episode.date ? ` (${episode.date})` : ''}${showCollection ? ` · ${episode.collectionTitle}` : ''}`},
            ])),
        },
        ['', ...options.map((episode) => String(episode.id))],
    ), [options.map((episode) => episode.id).join(','), showCollection]) // eslint-disable-line react-hooks/exhaustive-deps
    if (options.length === 0) return <span className="help">No episode looks like this file.</span>
    return (
        <SimpleSelect
            className="existing-files-pick"
            registry={registry}
            value={value ? String(value) : ''}
            onChange={(next) => onChange(next ? Number(next) : null)}
            aria-label={`Episode for ${file.path}`}
        />
    )
}
