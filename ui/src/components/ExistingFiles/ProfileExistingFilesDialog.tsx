import {useState} from 'react'
import {useQueryClient} from '@tanstack/react-query'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import toast from 'react-hot-toast'
import {faIcon} from '../../icons/faIcon'
import type {ExistingFile} from '../../types/schemas/existing_files'
import {Filter, filterOf, Results, SHOWN} from './ExistingFilesDialog'
import {adoptFiles, finishScan, useProfileExistingFiles} from './api'
import './ExistingFiles.css'

type Props = {
    localMediaProfileId: number
    localMediaProfileName: string
    onClose: () => void
}

type Match = {path: string, episodeId: number, collectionSlug: string}

function episodeOf(file: ExistingFile, episodeId: number) {
    return [file.episode, ...file.candidates].find((episode) => episode?.id === episodeId) ?? null
}

/** The open reviews of every Collection that uses one Local Media Profile, as one review of its folder. */
export default function ProfileExistingFilesDialog({localMediaProfileId, localMediaProfileName, onClose}: Props) {
    const qc = useQueryClient()
    const {data: review, refetch} = useProfileExistingFiles(localMediaProfileId)
    const [busy, setBusy] = useState<string | null>(null)
    const [filter, setFilter] = useState<Filter>('certain')
    const [picks, setPicks] = useState<Record<string, number>>({})
    const [shown, setShown] = useState(SHOWN)

    const files = review?.files ?? []
    const visible = files.filter((file) => filterOf(file) === filter)
    const toAdopt: Match[] = files
        .filter((file) => !file.adopted && file.episode && (file.confidence === 'certain' || file.confidence === 'likely'))
        .map((file) => ({path: file.path, episodeId: file.episode!.id, collectionSlug: file.episode!.collectionSlug}))
    const picked: Match[] = Object.entries(picks).flatMap(([path, episodeId]) => {
        const file = files.find((candidate) => candidate.path === path && !candidate.adopted)
        const episode = file ? episodeOf(file, episodeId) : null
        return episode ? [{path, episodeId, collectionSlug: episode.collectionSlug}] : []
    })
    const ready = (review?.collections ?? []).filter((scan) => scan.status === 'ready')
    const working = (review?.collections ?? []).filter((scan) => scan.status === 'waiting' || scan.status === 'scanning').length

    async function refresh() {
        await Promise.all([
            refetch(),
            qc.invalidateQueries({queryKey: ['existingFilesScans']}),
            qc.invalidateQueries({queryKey: ['existingFilesOpen']}),
            qc.invalidateQueries({queryKey: ['mediaDownloads']}),
            qc.invalidateQueries({queryKey: ['downloadProfilesView']}),
        ])
    }

    async function adopt(matches: Match[]) {
        if (matches.length === 0) return
        setBusy('adopt')
        try {
            // Each file is adopted through the scan of the Collection its episode belongs to.
            const bySlug = new Map<string, Match[]>()
            for (const match of matches) bySlug.set(match.collectionSlug, [...(bySlug.get(match.collectionSlug) ?? []), match])
            let adopted = 0
            const errors: {path: string, error: string}[] = []
            for (const [slug, group] of bySlug) {
                const result = await adoptFiles(slug, localMediaProfileId, group.map(({path, episodeId}) => ({path, episodeId})))
                adopted += result.adopted
                errors.push(...result.errors)
            }
            if (errors.length) toast.error(`${errors.length} file(s) were not adopted: ${errors[0].error}`)
            toast.success(`Adopted ${adopted} file${adopted === 1 ? '' : 's'}`)
            setPicks({})
            await refresh()
        } catch (exc) {
            toast.error(exc instanceof Error ? exc.message : 'Could not adopt the files')
        } finally {
            setBusy(null)
        }
    }

    async function finish() {
        setBusy('finish')
        try {
            let enabled = 0
            for (const scan of ready) enabled += (await finishScan(scan.collectionSlug, localMediaProfileId)).downloadProfilesEnabled
            if (enabled) {
                toast.success(`${enabled} Download Profile${enabled === 1 ? ' is' : 's are'} on and download${enabled === 1 ? 's' : ''} the episodes that have no file yet`)
            }
            await refresh()
            onClose()
        } catch (exc) {
            toast.error(exc instanceof Error ? exc.message : 'Could not finish')
        } finally {
            setBusy(null)
        }
    }

    return (
        <div className="modal-overlay" role="presentation">
            <div className="modal existing-files-dialog" role="dialog" aria-modal="true" aria-labelledby="profile-existing-files-title">
                <div className="modal-header">
                    <div className="modal-icon" aria-hidden><FontAwesomeIcon icon={faIcon('fass', 'file-import')}/></div>
                    <h2 id="profile-existing-files-title" className="modal-title">Match existing files</h2>
                </div>
                <div className="existing-files-body">
                    <p className="existing-files-intro">
                        Every file VODLoft found in {review?.folder ?? 'the folder'} of "{localMediaProfileName}", for
                        the {review?.collections.length ?? 0} collection{review?.collections.length === 1 ? '' : 's'} that
                        still have files to review. Adopted episodes are not downloaded again.
                    </p>
                    {working > 0 && (
                        <div className="form-info-card" role="status" aria-live="polite">
                            Still looking for files of {working} collection{working === 1 ? '' : 's'}.
                        </div>
                    )}
                    {review && (
                        <Results
                            scan={review}
                            showCollection
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
                    {ready.length > 0 && picked.length > 0 && (
                        <button type="button" className="btn" disabled={busy !== null} onClick={() => void adopt(picked)}>
                            Adopt {picked.length} checked
                        </button>
                    )}
                    {ready.length > 0 && toAdopt.length > 0 && (
                        <button type="button" className="btn btn-primary" disabled={busy !== null} onClick={() => void adopt(toAdopt)}>
                            {busy === 'adopt' ? 'Adopting…' : `Adopt ${toAdopt.length}`}
                        </button>
                    )}
                    {ready.length > 0 && (
                        <button type="button" className={toAdopt.length ? 'btn' : 'btn btn-primary'} disabled={busy !== null}
                                onClick={() => void finish()}>
                            {(review?.heldDownloadProfiles ?? 0) > 0 ? 'Done, download the rest' : 'Done'}
                        </button>
                    )}
                </div>
            </div>
        </div>
    )
}
