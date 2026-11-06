import {useEffect} from 'react'
import {useInfiniteQuery, useQueryClient} from '@tanstack/react-query'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import ProgressButton from '../common/ProgressButton'
import {useActiveOperation} from '../OperationNotifier/OperationNotifier'
import {frontendOperationDefinitions} from '../../lib/operationDefinitions'
import './CollectionSyncLogModal.css'
import {faIcon} from '../../icons/faIcon'
import {useLoadMoreOnScroll} from '../../lib/useLoadMoreOnScroll'

type Props = {
  collectionId: number
  collectionSlug: string
  collectionTitle: string
  open: boolean
  /** While Sync now is asking the backend to start its scan, before the scan's operation is known. */
  starting: boolean
  onClose: () => void
  onSyncNow: () => void | Promise<void>
  onCancelSync?: () => void
  cancelSyncDisabled?: boolean
}

/** One scan that looked at the Collection: a full scan or a quick check. */
type CollectionScan = {
  id: number
  kind: 'full_scan' | 'quick_check'
  status: 'SUCCEEDED' | 'FAILED' | 'CANCELED'
  ranAt: string | null
  episodesFound: number | null
}

type CollectionSyncLog = {items: CollectionScan[], total: number}

const PAGE_SIZE = 25

const SCAN_KIND_LABELS: Record<CollectionScan['kind'], string> = {
  full_scan: 'Full scan',
  quick_check: 'Quick check',
}

function episodeCount(scan: CollectionScan): string | number {
  if (scan.status === 'FAILED') return 'Failed'
  if (scan.status === 'CANCELED') return 'Canceled'
  return scan.episodesFound ?? 0
}

function formatDate(value: string | null | undefined): string {
  if (!value) return '—'
  const normalized = /(?:Z|[+-]\d\d:\d\d)$/i.test(value) ? value : `${value}Z`
  return new Date(normalized).toLocaleString()
}

export default function CollectionSyncLogModal({
  collectionId, collectionSlug, collectionTitle, open, starting, onClose, onSyncNow, onCancelSync, cancelSyncDisabled,
}: Props) {
  const queryClient = useQueryClient()
  const scanOperation = useActiveOperation('collection.sync', 'collection', collectionId)
  const scanning = starting || scanOperation !== undefined

  const log = useInfiniteQuery({
    queryKey: ['collection', collectionSlug, 'syncLog'],
    enabled: open,
    initialPageParam: 0,
    getNextPageParam: (last: CollectionSyncLog, pages: CollectionSyncLog[]) => {
      const loaded = pages.reduce((count, part) => count + part.items.length, 0)
      return last.items.length > 0 && loaded < last.total ? loaded : undefined
    },
    queryFn: async ({signal, pageParam}): Promise<CollectionSyncLog> => {
      const params = new URLSearchParams({offset: String(pageParam), limit: String(PAGE_SIZE)})
      const r = await fetch(
        `${(window as any).appConfig.API_URL}/collections/${encodeURIComponent(collectionSlug)}/sync-log?${params}`,
        {signal, credentials: 'include'},
      )
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      return r.json()
    },
  })

  // A sync that just finished belongs at the top of the log.
  useEffect(() => {
    if (!scanning) void queryClient.invalidateQueries({queryKey: ['collection', collectionSlug, 'syncLog']})
  }, [scanning, collectionSlug, queryClient])

  const entries = log.data?.pages.flatMap((part) => part.items) ?? []
  const loadingMore = log.isFetchingNextPage
  const moreFailed = log.isFetchNextPageError
  const {rootRef, endRef} = useLoadMoreOnScroll<HTMLDivElement, HTMLDivElement>(
    open && log.hasNextPage && !loadingMore && !moreFailed,
    () => void log.fetchNextPage(),
  )

  if (!open) return null

  return (
    <div className="modal-overlay" role="presentation" onClick={onClose}>
      <div
        className="modal collection-sync-log-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="collection-sync-log-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="modal-header collection-sync-log-header">
          <div className="modal-icon" aria-hidden>
            <FontAwesomeIcon icon={faIcon('fass', 'arrows-rotate')} />
          </div>
          <div>
            <h2 id="collection-sync-log-title" className="modal-title">Sync log</h2>
            <div className="collection-sync-log-subtitle">{collectionTitle}</div>
          </div>
        </div>

        <div className="collection-sync-log-content" ref={rootRef}>
          {log.isLoading ? (
            <p className="modal-text">Loading sync history...</p>
          ) : log.isError && entries.length === 0 ? (
            <p className="modal-text">Could not load sync history.</p>
          ) : entries.length === 0 ? (
            <p className="modal-text">No syncs have been recorded yet.</p>
          ) : (
            <div className="collection-sync-log-table" role="table" aria-label="Recent syncs">
              <div className="collection-sync-log-row collection-sync-log-row-header" role="row">
                <span role="columnheader">Ran</span>
                <span role="columnheader">Episodes found</span>
              </div>
              {entries.map((entry) => (
                <div className="collection-sync-log-row" role="row" key={entry.id}>
                  <span role="cell">
                    <span className="collection-sync-log-ran">{formatDate(entry.ranAt)}</span>
                    <span className="collection-sync-log-kind">{SCAN_KIND_LABELS[entry.kind]}</span>
                  </span>
                  <span
                    role="cell"
                    className={entry.status === 'FAILED' ? 'collection-sync-log-failed' : undefined}
                  >
                    {episodeCount(entry)}
                  </span>
                </div>
              ))}
            </div>
          )}
          {entries.length > 0 && (
            <div className="collection-sync-log-more" ref={endRef} aria-live="polite">
              {moreFailed ? (
                <>
                  Could not load more syncs.
                  <button type="button" className="btn" onClick={() => void log.fetchNextPage()}>Try again</button>
                </>
              ) : loadingMore ? 'Loading more syncs…' : null}
            </div>
          )}
        </div>

        <div className="collection-sync-log-footer">
          <div className="modal-actions collection-sync-log-actions">
            <button type="button" className="btn" onClick={onClose}>Close</button>
            <ProgressButton
              definition={frontendOperationDefinitions['collection.sync']}
              resourceId={collectionId}
              label="Sync now"
              icon={faIcon('fass', 'arrows-rotate')}
              onClick={() => {
                // The page's Scanning banner follows the sync from here.
                onClose()
                void onSyncNow()
              }}
              starting={starting}
              onCancel={onCancelSync}
              cancelDisabled={cancelSyncDisabled}
              cancelLabel="Cancel sync"
            />
          </div>
        </div>
      </div>
    </div>
  )
}
