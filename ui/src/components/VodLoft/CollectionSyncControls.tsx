import {useEffect, useRef, useState} from 'react'
import {vodloftApi as api} from '../../lib/vodloftApi'
import ProgressButton from '../common/ProgressButton'
import {frontendOperationDefinitions as definitions} from '../../lib/operationDefinitions'
import type {TaskOperationRead} from '../../types/schemas/operation'
import './Discovery.css'

type Scan = {id: number; source_id: string; source_reference_id: number | null; status: string; mode: string;
    entry_count: number; removed_count: number; complete: boolean; error: string | null;
    error_code: string | null; attempts: number; retry_at: string | null; has_checkpoint: boolean;
    runtime_version: string | null; created_at: string}
const activeStatuses = ['QUEUED', 'RUNNING', 'WAITING']

export default function CollectionSyncControls({collectionId, referenceId, canSync, reason, onRefreshed}: {
    collectionId: number; referenceId: number | null; canSync: boolean; reason?: string; onRefreshed: () => void;
}) {
    const [operations, setOperations] = useState<TaskOperationRead[]>([])
    const [scans, setScans] = useState<Scan[]>([])
    const [starting, setStarting] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [showHistory, setShowHistory] = useState(false)
    const previousStatuses = useRef<Record<string, string>>({})
    const callback = useRef(onRefreshed); callback.current = onRefreshed
    const refresh = async (signal?: AbortSignal) => {
        const [next, history] = await Promise.all([api<TaskOperationRead[]>(`/library/${collectionId}/operations`, {signal}),
            api<Scan[]>(`/library/${collectionId}/scans`, {signal})])
        if (signal?.aborted) return
        const completed = next.some(operation => activeStatuses.includes(previousStatuses.current[operation.id]) && !activeStatuses.includes(operation.status))
        previousStatuses.current = Object.fromEntries(next.map(operation => [operation.id, operation.status]))
        setOperations(next); setScans(history)
        if (completed) callback.current()
    }
    useEffect(() => {
        const controller = new AbortController(); previousStatuses.current = {}
        const load = () => void refresh(controller.signal).catch(e => {if (!controller.signal.aborted) setError(String(e))})
        load(); const timer = window.setInterval(load, 2500)
        return () => {controller.abort(); window.clearInterval(timer)}
    }, [collectionId])
    const scoped = operations.filter(operation => operation.context?.source_reference_id === referenceId)
    const active = scoped.find(operation => activeStatuses.includes(operation.status))
    const latest = scoped[0]
    const start = async (depth = 0) => {
        setStarting(true); setError(null)
        try {
            await api(`/library/${collectionId}/sync`, {method: 'POST', body: JSON.stringify({
                reference_id: referenceId, full_scan: true, expand_depth: depth, max_nested: 20})})
            await refresh()
        } catch (e) {setError(String(e))} finally {setStarting(false)}
    }
    const control = async (operationId: string, action: 'cancel' | 'resume') => {
        setError(null)
        try {await api(`/library/${collectionId}/operations/${operationId}/${action}`, {method: 'POST'}); await refresh()}
        catch (e) {setError(String(e))}
    }
    return <section aria-label="Collection synchronization">
        <div className="vodloft-fields">
            <ProgressButton definition={definitions.vodloft_collection_sync}
                label="Refresh Collection" disabled={!referenceId || !canSync} starting={starting} active={!!active}
                activeLabel={active?.message || (active?.status === 'QUEUED' ? 'Queued…' : undefined)}
                onClick={() => void start()} onCancel={active ? () => void control(active.id, 'cancel') : undefined}/>
            <button className="btn" type="button" disabled={!referenceId || !canSync || starting || !!active}
                onClick={() => void start(2)}>Expand nested Collections (2 levels, 20 max)</button>
            <button className="btn" type="button" onClick={() => setShowHistory(current => !current)}>{showHistory ? 'Hide scan history' : 'Scan history'}</button>
        </div>
        {!canSync && referenceId && <p>{reason || 'This Source/account cannot enumerate this Collection.'}</p>}
        {latest && !active && <p role="status">{latest.message}{latest.error && ` · ${latest.error}`}
            {['FAILED', 'PARTIAL', 'CANCELED'].includes(latest.status) && canSync && <>{' '}
                <button type="button" className="btn" onClick={() => void control(latest.id, 'resume')}>Resume refresh</button></>}</p>}
        {showHistory && <div className="vodloft-scan-history"><table><thead><tr>
            <th>Started</th><th>Source</th><th>Scan</th><th>Members</th><th>Removed memberships</th><th>State</th>
        </tr></thead><tbody>{scans.filter(scan => !referenceId || scan.source_reference_id === referenceId).map(scan => <tr key={scan.id}>
            <td>{new Date(scan.created_at).toLocaleString()}</td><td>{scan.source_id} {scan.runtime_version}</td><td>{scan.mode}</td>
            <td>{scan.entry_count}</td><td>{scan.removed_count}</td><td>{scan.status}{scan.has_checkpoint && ' · continuation saved'}
                {scan.error && <p>{scan.error}</p>}{scan.retry_at && <p>Retry after {new Date(scan.retry_at).toLocaleString()}</p>}</td>
        </tr>)}</tbody></table><p>Only complete scans retire missing memberships. Local media stays available.</p></div>}
        {error && <p role="alert">{error}</p>}
    </section>
}
