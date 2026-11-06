import {useEffect} from 'react'
import {useInfiniteQuery, useQueryClient} from '@tanstack/react-query'
import ProgressButton from '../common/ProgressButton'
import {useActiveOperation} from '../OperationNotifier/OperationNotifier'
import {frontendOperationDefinitions} from '../../lib/operationDefinitions'
import LedgerModal, {formatLedgerDate} from '../common/LedgerModal'
import {faIcon} from '../../icons/faIcon'
import {apiUrl, responseError} from '../../lib/api'

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
        `${apiUrl()}/collections/${encodeURIComponent(collectionSlug)}/sync-log?${params}`,
        {signal, credentials: 'include'},
      )
      if (!r.ok) throw await responseError(r)
      return r.json()
    },
  })

  // A sync that just finished belongs at the top of the log.
  useEffect(() => {
    if (!scanning) void queryClient.invalidateQueries({queryKey: ['collection', collectionSlug, 'syncLog']})
  }, [scanning, collectionSlug, queryClient])

  return (
    <LedgerModal<CollectionScan>
      open={open}
      title="Sync log"
      subtitle={collectionTitle}
      icon={faIcon('fass', 'arrows-rotate')}
      noun="syncs"
      tableLabel="Recent syncs"
      pages={{...log, items: log.data?.pages.flatMap((part) => part.items) ?? []}}
      gridColumns="minmax(0, 1fr) auto"
      rowKey={(entry) => entry.id}
      columns={[
        {
          header: 'Ran',
          cell: (entry) => (
            <span className="ledger-modal__detail">
              <span>{formatLedgerDate(entry.ranAt)}</span>
              <small>{SCAN_KIND_LABELS[entry.kind]}</small>
            </span>
          ),
        },
        {
          header: 'Episodes found',
          cell: (entry) => <span className={entry.status === 'FAILED' ? 'is-failed' : undefined}>{episodeCount(entry)}</span>,
        },
      ]}
      onClose={onClose}
      actions={
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
      }
    />
  )
}
