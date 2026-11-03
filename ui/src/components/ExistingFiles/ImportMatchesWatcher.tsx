import {useEffect, useState} from 'react'
import {useNavigate} from 'react-router-dom'
import toast from 'react-hot-toast'
import {readRun} from '../../lib/imports'
import type {ImportRun} from '../../types/schemas/imports'

/** Imports whose Match existing files scans are still running, kept across page loads and onboarding. */
const STORAGE_KEY = 'vodloft.importMatches'
const CHANGED = 'vodloft:import-matches'
const POLL_MS = 5000

type Watched = {importer: string, runId: number}

function readWatched(): Watched[] {
    try {
        const value = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? '[]')
        return Array.isArray(value) ? value.filter((item) => typeof item?.importer === 'string' && typeof item?.runId === 'number') : []
    } catch {
        return []
    }
}

function writeWatched(items: Watched[]) {
    try {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(items))
    } catch {
        // Without storage the toast only shows while this page stays open.
    }
    window.dispatchEvent(new Event(CHANGED))
}

/** Show a toast once this import's Match existing files scans are done. */
export function watchImportMatches(importer: string, runId: number) {
    writeWatched([...readWatched().filter((item) => item.runId !== runId || item.importer !== importer), {importer, runId}])
}

function scansDone(run: ImportRun): boolean {
    if (run.status === 'failed') return true
    if (run.status !== 'finished') return false
    return run.steps.every((step) => !step.matching || !['waiting', 'scanning'].includes(step.matching.status))
}

function message(run: ImportRun): string {
    const matched = run.steps.filter((step) => step.matching)
    const found = matched.reduce((total, step) => total + (step.matching?.found ?? 0), 0)
    const collections = matched.filter((step) => (step.matching?.found ?? 0) > 0).length
    const failed = matched.filter((step) => step.matching?.status === 'failed').length
    const parts = [found > 0
        ? `Match existing files found ${found} file${found === 1 ? '' : 's'} in ${collections} collection${collections === 1 ? '' : 's'}.`
        : 'Match existing files found no other files.']
    if (failed) parts.push(`${failed} scan${failed === 1 ? '' : 's'} failed.`)
    if (matched.some((step) => step.matching?.status === 'ready')) parts.push('Review them to adopt the files and start the downloads.')
    return parts.join(' ')
}

/** Watches imports that match existing files afterwards, and shows a toast that stays until it is closed. */
export default function ImportMatchesWatcher() {
    const navigate = useNavigate()
    const [watched, setWatched] = useState<Watched[]>(readWatched)

    useEffect(() => {
        const update = () => setWatched(readWatched())
        window.addEventListener(CHANGED, update)
        window.addEventListener('storage', update)
        return () => {
            window.removeEventListener(CHANGED, update)
            window.removeEventListener('storage', update)
        }
    }, [])

    useEffect(() => {
        if (watched.length === 0) return
        let stopped = false
        const check = async () => {
            for (const item of watched) {
                let run: ImportRun
                try {
                    run = await readRun(item.importer, item.runId)
                } catch {
                    continue
                }
                if (stopped || !scansDone(run)) continue
                writeWatched(readWatched().filter((other) => other.runId !== item.runId || other.importer !== item.importer))
                if (run.status !== 'finished' || !run.steps.some((step) => step.matching)) continue
                toast((t) => (
                    <div className="import-matches-toast">
                        <span>{message(run)}</span>
                        <span className="import-matches-toast__actions">
                            <button type="button" className="btn btn-primary" onClick={() => {
                                toast.dismiss(t.id)
                                navigate('/existing-files')
                            }}>Review matches</button>
                            <button type="button" className="btn" onClick={() => toast.dismiss(t.id)}>Close</button>
                        </span>
                    </div>
                ), {id: `import-matches-${item.importer}-${item.runId}`, duration: Infinity})
            }
        }
        const timer = window.setInterval(() => void check(), POLL_MS)
        void check()
        return () => {
            stopped = true
            window.clearInterval(timer)
        }
    }, [watched, navigate])

    return null
}
