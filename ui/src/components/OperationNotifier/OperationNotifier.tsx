import {
  createContext,
  type ReactNode,
  useContext,
  useEffect,
  useMemo,
  useRef,
} from 'react'
import {useQueryClient} from '@tanstack/react-query'
import {toast} from 'react-hot-toast'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import {type TaskOperationRead} from '../../types/schemas/operation'
import {invalidateForOperations} from '../../lib/operationInvalidation'
import {refreshFrontendPuller, useFrontendPuller} from '../../lib/puller'
import {type OperationNotificationDefinitions} from './OperationNotificationDefinitions'
import {apiUrl} from '../../lib/api'

const ACTIVE_STATUSES = new Set(['QUEUED', 'RUNNING', 'WAITING'])
const TERMINAL_STATUSES = new Set(['SUCCEEDED', 'PARTIAL', 'FAILED', 'CANCELED'])

type OperationContextValue = {
  operations: TaskOperationRead[]
  findActive: (
    kind: string,
    resourceType?: string,
    resourceId?: number | null,
  ) => TaskOperationRead | undefined
}

const OperationContext = createContext<OperationContextValue>({
  operations: [],
  findActive: () => undefined,
})

async function markSeen(operationIds: string[]): Promise<void> {
  const base = apiUrl()
  const response = await fetch(`${base}/operations/seen`, {
    method: 'POST',
    credentials: 'include',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({operationIds}),
  })
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
}

function resultNumber(operation: TaskOperationRead, key: string): number | undefined {
  const value = operation.result?.data?.[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function terminalMessage(
  operation: TaskOperationRead,
  definitions: OperationNotificationDefinitions,
): string {
  const definition = definitions[operation.kind]
  const label = definition?.label || operation.title || 'Operation'

  if (operation.status === 'SUCCEEDED') {
    return definition?.success?.(operation)
      ?? operation.result?.summary
      ?? operation.message
      ?? `${operation.title} completed`
  }

  if (operation.status === 'PARTIAL') {
    if (definition?.partial) return definition.partial(operation)
    const completed = resultNumber(operation, 'completed') ?? operation.progressCurrent
    const total = resultNumber(operation, 'total') ?? operation.progressTotal
    return `${label} partially completed for ${operation.title}: ${completed}/${total} tasks succeeded`
  }

  if (operation.status === 'CANCELED') {
    if (definition?.canceled) return definition.canceled(operation)
    if (operation.message && operation.message !== 'Canceled by user') {
      return `${label} stopped for ${operation.title}: ${operation.message}`
    }
    return `${label} was canceled for ${operation.title}`
  }

  if (definition?.failed) return definition.failed(operation)
  return `${label} failed for ${operation.title}${operation.error ? `: ${operation.error}` : ''}`
}

export default function OperationNotifier({
  children,
  definitions,
}: {
  children: ReactNode
  definitions: OperationNotificationDefinitions
}) {
  const queryClient = useQueryClient()
  const handledRef = useRef(new Set<string>())
  const previousActiveRef = useRef(new Map<string, TaskOperationRead>())
  const {data: pullData} = useFrontendPuller()
  const operations = pullData?.operations ?? []

  // If another browser acknowledges a terminal operation before this browser
  // observes the terminal snapshot, it disappears from the pull. Remembering the
  // active snapshot still lets this browser refresh the affected ordinary queries.
  useEffect(() => {
    if (!pullData) return

    const currentById = new Map(operations.map((operation) => [operation.id, operation]))
    const currentActive = new Map(
      operations
        .filter((operation) => ACTIVE_STATUSES.has(operation.status))
        .map((operation) => [operation.id, operation]),
    )

    const vanished = [...previousActiveRef.current]
      .filter(([operationId]) => !currentActive.has(operationId) && !currentById.has(operationId))
      .map(([, previous]) => previous)
    void invalidateForOperations(queryClient, vanished)
    previousActiveRef.current = currentActive
  }, [operations, pullData, queryClient])

  // A finished operation's domain-data refresh runs in every browser that sees
  // it. An operation started from the UI also gets a toast and stays in the pull
  // until a browser acknowledges that toast; automated and API work leaves the
  // pull by itself a while after it finished.
  //
  // A page opened after a quiet night finds everything the scheduled work
  // finished meanwhile, so the operations a pull brings are refreshed,
  // acknowledged and pulled again together: one round for all of them.
  useEffect(() => {
    const finished: TaskOperationRead[] = []
    for (const operation of operations) {
      if (
        !TERMINAL_STATUSES.has(operation.status)
        || handledRef.current.has(operation.id)
      ) {
        continue
      }

      handledRef.current.add(operation.id)
      finished.push(operation)
      if (operation.source === 'UI' && !operation.notificationSeenAt) {
        const message = terminalMessage(operation, definitions)
        const action = operation.status === 'SUCCEEDED'
          ? definitions[operation.kind]?.successAction?.(operation)
          : undefined
        if (action) {
          // Long enough to come back to the tab and press it.
          toast.success((t) => (
            <span className="toast-with-action">
              <span>{message}</span>
              <a className="btn btn-primary" href={action.href} download={action.download}
                 onClick={() => toast.dismiss(t.id)}>
                {action.label}
              </a>
              {/* It stays up a long time (and while touched on a phone), so it can be closed by hand. */}
              <button type="button" className="toast-close" aria-label="Close" title="Close"
                      onClick={() => toast.dismiss(t.id)}>
                <FontAwesomeIcon icon={faIcon('fass', 'xmark')} aria-hidden="true"/>
              </button>
            </span>
          ), {duration: 60_000})
        } else if (operation.status === 'SUCCEEDED') {
          toast.success(message, {duration: 5000})
        } else if (operation.status === 'PARTIAL' || operation.status === 'CANCELED') {
          toast(message, {duration: 6000})
        } else {
          toast.error(message, {duration: 6000})
        }
      }
    }
    if (finished.length === 0) return

    const unseen = finished
      .filter((operation) => operation.source === 'UI' && !operation.notificationSeenAt)
      .map((operation) => operation.id)
    void (async () => {
      try {
        await invalidateForOperations(queryClient, finished)
        if (unseen.length > 0) {
          await markSeen(unseen)
          await refreshFrontendPuller(queryClient)
        }
      } catch {
        // Leave unacknowledged operations durable server-side so a later
        // browser reload can retry the cache refresh/acknowledgement path.
      }
    })()
  }, [definitions, operations, queryClient])

  const value = useMemo<OperationContextValue>(() => ({
    operations,
    findActive: (kind, resourceType, resourceId) => operations.find((operation) => (
      ACTIVE_STATUSES.has(operation.status)
      && operation.kind === kind
      && (resourceType === undefined || operation.resourceType === resourceType)
      && (resourceId === undefined || operation.resourceId === resourceId)
    )),
  }), [operations])

  return (
    <OperationContext.Provider value={value}>
      {children}
    </OperationContext.Provider>
  )
}

export function useOperations() {
  return useContext(OperationContext)
}

export function useActiveOperation(
  kind: string,
  resourceType?: string,
  resourceId?: number | null,
) {
  const {findActive} = useOperations()
  if (resourceId === null) return undefined
  return findActive(kind, resourceType, resourceId)
}
