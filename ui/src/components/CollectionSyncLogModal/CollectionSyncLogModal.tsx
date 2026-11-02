import {useEffect, useState} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {useCollection} from '../../lib/queries'
import {useTaskLedgerInfinite} from '../../lib/taskLedger'
import {TaskLedgerEntryRead} from '../../types/schemas/task'
import './CollectionSyncLogModal.css'
import {faIcon} from '../../icons/faIcon'

type Props = {
  collectionSlug: string
  collectionTitle: string
  open: boolean
  syncing: boolean
  onClose: () => void
  onSyncNow: () => void | Promise<void>
}

const PAGE_SIZE = 10
const TERMINAL_STATUSES = ['SUCCEEDED', 'FAILED', 'CANCELED'] as const

function resultData(run: TaskLedgerEntryRead): Record<string, unknown> {
  const result = run.result
  if (!result || typeof result !== 'object') return {}
  const data = result.data
  return data && typeof data === 'object' && !Array.isArray(data)
    ? data as Record<string, unknown>
    : {}
}

function collectionResult(run: TaskLedgerEntryRead, collectionId: number): Record<string, unknown> | null {
  const data = resultData(run)
  if (run.resourceId === collectionId) return data
  if (run.resourceId !== null) return null

  const collections = Array.isArray(data.collections) ? data.collections : []
  const matching = collections.find((item) => {
    if (!item || typeof item !== 'object') return false
    return Number((item as Record<string, unknown>).collection_id) === collectionId
  })
  if (matching && typeof matching === 'object') return matching as Record<string, unknown>

  // Global fetches are scoped to every collection that existed when they ran. The
  // ledger query starts at this collection's creation time, so keep the row even if a
  // failed/canceled run (or an older result shape) has no per-collection payload.
  return {}
}

function episodeCount(run: TaskLedgerEntryRead, collectionId: number): string | number {
  if (run.status === 'FAILED') return 'Failed'
  if (run.status === 'CANCELED') return 'Canceled'
  const found = collectionResult(run, collectionId)?.episodes_found
  return typeof found === 'number' && Number.isFinite(found) ? found : '—'
}

function formatDate(value: string | null | undefined): string {
  if (!value) return '—'
  const normalized = /(?:Z|[+-]\d\d:\d\d)$/i.test(value) ? value : `${value}Z`
  return new Date(normalized).toLocaleString()
}

export default function CollectionSyncLogModal({collectionSlug, collectionTitle, open, syncing, onClose, onSyncNow}: Props) {
  const {data: collection} = useCollection(collectionSlug)
  const collectionId = collection?.id
  const [page, setPage] = useState(1)

  useEffect(() => {
    if (open) setPage(1)
  }, [open, collectionSlug])

  // Global scans have no resource; their results list each show they scanned.
  const ledger = useTaskLedgerInfinite({
    definitionKey: 'fetch_new_episodes',
    resourceType: 'collection',
    resourceId: collectionId === undefined ? undefined : [collectionId],
    includeUnscoped: true,
    status: TERMINAL_STATUSES,
    startedAfter: collection?.createdAt,
    orderBy: 'created_at',
    order: 'desc',
    limit: PAGE_SIZE,
    enabled: open && collectionId !== undefined,
  })

  const total = ledger.total
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const totalIsProvisional = ledger.isTotalProvisional
  const pageStart = (page - 1) * PAGE_SIZE
  const entries = ledger.items.slice(pageStart, pageStart + PAGE_SIZE)

  useEffect(() => {
    if (page > totalPages) setPage(totalPages)
  }, [page, totalPages])

  const showNextPage = async () => {
    if (page >= totalPages || ledger.isFetching) return

    const nextPage = page + 1
    const requiredRows = nextPage * PAGE_SIZE
    if (ledger.items.length < requiredRows && ledger.hasNextPage) {
      const result = await ledger.fetchNextPage()
      if (result.isError) return
    }
    setPage(nextPage)
  }

  if (!open) return null

  return (
    <div className="modal-overlay" role="presentation" onClick={onClose}>
      <div
        className="modal show-sync-log-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="collection-sync-log-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="modal-header show-sync-log-header">
          <div className="modal-icon" aria-hidden>
            <FontAwesomeIcon icon={faIcon('fass', 'arrows-rotate')} />
          </div>
          <div>
            <h2 id="collection-sync-log-title" className="modal-title">Sync log</h2>
            <div className="collection-sync-log-subtitle">{collectionTitle}</div>
          </div>
        </div>

        <div className="collection-sync-log-content">
          {ledger.isLoading ? (
            <p className="modal-text">Loading sync history...</p>
          ) : ledger.isError ? (
            <p className="modal-text">Could not load sync history.</p>
          ) : entries.length === 0 ? (
            <p className="modal-text">No syncs have been recorded yet.</p>
          ) : (
            <div className="collection-sync-log-table" role="table" aria-label="Recent syncs">
              <div className="show-sync-log-row show-sync-log-row-header" role="row">
                <span role="columnheader">Ran</span>
                <span role="columnheader">Episodes found</span>
              </div>
              {entries.map((entry) => (
                <div className="collection-sync-log-row" role="row" key={entry.id}>
                  <span role="cell">{formatDate(entry.finishedAt ?? entry.startedAt)}</span>
                  <span
                    role="cell"
                    className={entry.status === 'FAILED' ? 'collection-sync-log-failed' : undefined}
                  >
                    {collectionId === undefined ? '—' : episodeCount(entry, collectionId)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="collection-sync-log-footer">
          <nav className="collection-sync-log-pagination" aria-label="Sync log pages">
            <button
              type="button"
              className="btn"
              disabled={page <= 1 || ledger.isFetching}
              onClick={() => setPage((current) => Math.max(1, current - 1))}
            >
              Previous
            </button>
            <span className="collection-sync-log-page-label" aria-live="polite">
              {totalIsProvisional ? `Page ${page}` : `Page ${page} of ${totalPages}`}
            </span>
            <button
              type="button"
              className="btn"
              disabled={page >= totalPages || ledger.isFetching}
              onClick={() => void showNextPage()}
            >
              Next
            </button>
          </nav>

          <div className="modal-actions show-sync-log-actions">
            <button type="button" className="btn" onClick={onClose}>Close</button>
            <button type="button" className="btn btn-primary" onClick={() => void onSyncNow()} disabled={syncing}>
              <FontAwesomeIcon icon={faIcon('fass', syncing ? 'spinner' : 'arrows-rotate')} spin={syncing} aria-hidden="true" />
              <span>{syncing ? 'Syncing...' : 'Sync now'}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
