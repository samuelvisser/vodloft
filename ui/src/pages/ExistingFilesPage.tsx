import {useState} from 'react'
import {Link} from 'react-router-dom'
import {useQueryClient} from '@tanstack/react-query'
import toast from 'react-hot-toast'
import PageSubtitle from '../components/common/PageSubtitle'
import ProgressBar from '../components/common/ProgressBar'
import ExistingFilesDialog from '../components/ExistingFiles/ExistingFilesDialog'
import {adoptFiles, finishScan, readScan, useOpenExistingFilesScans} from '../components/ExistingFiles/api'
import type {ExistingFilesOpenScan} from '../types/schemas/existing_files'
import '../components/ExistingFiles/ExistingFiles.css'

const STATUS_LABELS: Record<ExistingFilesOpenScan['status'], string> = {
    waiting: 'Waiting for indexing',
    scanning: 'Looking for files…',
    ready: 'Ready to review',
    failed: 'Failed',
    finished: 'Done',
    none: 'Not scanned',
}

const sure = (scan: ExistingFilesOpenScan) => scan.counts.certain + scan.counts.likely

/** Every Collection's Match existing files results that still need a person, in one place. */
export default function ExistingFilesPage() {
    const qc = useQueryClient()
    const {data: scans, isLoading, error} = useOpenExistingFilesScans()
    const [open, setOpen] = useState<ExistingFilesOpenScan | null>(null)
    const [busy, setBusy] = useState<{label: string, done: number, total: number} | null>(null)

    const ready = (scans ?? []).filter((scan) => scan.status === 'ready')
    const toAdopt = ready.filter((scan) => sure(scan) > 0)
    const adoptable = toAdopt.reduce((total, scan) => total + sure(scan), 0)
    const working = (scans ?? []).filter((scan) => scan.status === 'waiting' || scan.status === 'scanning').length

    async function refresh() {
        await Promise.all([
            qc.invalidateQueries({queryKey: ['existingFilesOpen']}),
            qc.invalidateQueries({queryKey: ['existingFilesScans']}),
            qc.invalidateQueries({queryKey: ['mediaDownloads']}),
            qc.invalidateQueries({queryKey: ['downloadProfilesView']}),
        ])
    }

    async function adoptAll() {
        setBusy({label: 'Adopting the matches', done: 0, total: toAdopt.length})
        let adopted = 0
        let failed = 0
        try {
            for (const [index, scan] of toAdopt.entries()) {
                const detail = await readScan(scan.collectionSlug, scan.localMediaProfileId)
                const matches = detail.files
                    .filter((file) => !file.adopted && file.episode && (file.confidence === 'certain' || file.confidence === 'likely'))
                    .map((file) => ({path: file.path, episodeId: file.episode!.id}))
                const result = await adoptFiles(scan.collectionSlug, scan.localMediaProfileId, matches)
                adopted += result.adopted
                failed += result.errors.length
                setBusy({label: 'Adopting the matches', done: index + 1, total: toAdopt.length})
            }
            toast.success(`Adopted ${adopted} file${adopted === 1 ? '' : 's'}`)
            if (failed) toast.error(`${failed} file${failed === 1 ? ' was' : 's were'} not adopted; open its collection to see why`)
        } catch (exc) {
            toast.error(exc instanceof Error ? exc.message : 'Could not adopt the files')
        } finally {
            setBusy(null)
            await refresh()
        }
    }

    async function finishAll() {
        setBusy({label: 'Finishing', done: 0, total: ready.length})
        let enabled = 0
        try {
            for (const [index, scan] of ready.entries()) {
                enabled += (await finishScan(scan.collectionSlug, scan.localMediaProfileId)).downloadProfilesEnabled
                setBusy({label: 'Finishing', done: index + 1, total: ready.length})
            }
            toast.success(enabled
                ? `Done. ${enabled} Download Profile${enabled === 1 ? ' is' : 's are'} on and download${enabled === 1 ? 's' : ''} the episodes without a file`
                : 'Done')
        } catch (exc) {
            toast.error(exc instanceof Error ? exc.message : 'Could not finish')
        } finally {
            setBusy(null)
            await refresh()
        }
    }

    return (
        <section className="view existing-files-page" aria-labelledby="existing-files-title">
            <div className="view-header">
                <h1 id="existing-files-title">Match existing files</h1>
                <PageSubtitle summary={<>Files already on disk that VODLoft found for your collections.</>}>
                    <p>VODLoft looked in each Local Media Profile's folder for files it doesn't know yet, like files
                        with an older name, and matched them to episodes. Adopted files count as downloaded, so those
                        episodes are not downloaded again.</p>
                    <p>Download Profiles that wait for a collection start once you are done with it.</p>
                </PageSubtitle>
            </div>

            {error && <p className="form-error-card" role="alert">{error.message}</p>}
            {isLoading && <ProgressBar ariaLabel="Loading" value={null}/>}
            {scans && scans.length === 0 && <p className="help">Nothing to review. Every scan is done.</p>}

            {scans && scans.length > 0 && (
                <>
                    <div className="existing-files-page__actions">
                        {working > 0 && <span className="help">Still looking in {working} collection{working === 1 ? '' : 's'}…</span>}
                        <button type="button" className="btn btn-primary" disabled={busy !== null || adoptable === 0} onClick={() => void adoptAll()}>
                            Adopt {adoptable} certain and likely match{adoptable === 1 ? '' : 'es'}
                        </button>
                        <button type="button" className="btn" disabled={busy !== null || ready.length === 0} onClick={() => void finishAll()}>
                            Done with all, download the rest
                        </button>
                    </div>
                    {busy && (
                        <ProgressBar ariaLabel={busy.label} value={busy.total ? 100 * busy.done / busy.total : null}
                                     detail={`${busy.label}: ${busy.done} of ${busy.total} collections`}/>
                    )}
                    <ul className="existing-files-page__list">
                        {scans.map((scan) => (
                            <li key={`${scan.collectionSlug}-${scan.localMediaProfileId}`} className="existing-files-page__item">
                                <div className="existing-files-page__title">
                                    <Link to={`/collection/${scan.collectionSlug}`}>{scan.collectionTitle}</Link>
                                    <small>{scan.localMediaProfileName} · {scan.folder}</small>
                                </div>
                                <div className="existing-files-page__counts">
                                    {scan.status === 'ready' ? (
                                        <>
                                            <span className="existing-files-chip is-certain">{scan.counts.certain} certain</span>
                                            <span className="existing-files-chip is-likely">{scan.counts.likely} likely</span>
                                            <span className="existing-files-chip is-review">{scan.counts.review} to check</span>
                                            {scan.counts.adopted > 0 && <span className="existing-files-chip">{scan.counts.adopted} adopted</span>}
                                        </>
                                    ) : (
                                        <span className="existing-files-chip">{STATUS_LABELS[scan.status]}</span>
                                    )}
                                    {scan.heldDownloadProfiles > 0 && <span className="help">Downloads wait</span>}
                                </div>
                                {scan.error && <p className="form-error-card" role="alert">{scan.error}</p>}
                                <button type="button" className="btn" disabled={busy !== null} onClick={() => setOpen(scan)}>
                                    {scan.status === 'ready' ? 'Review' : 'Open'}
                                </button>
                            </li>
                        ))}
                    </ul>
                </>
            )}

            {open && (
                <ExistingFilesDialog
                    collectionSlug={open.collectionSlug}
                    collectionTitle={open.collectionTitle}
                    profiles={[{id: open.localMediaProfileId, name: open.localMediaProfileName}]}
                    initialProfileId={open.localMediaProfileId}
                    onClose={() => {
                        setOpen(null)
                        void refresh()
                    }}
                />
            )}
        </section>
    )
}
