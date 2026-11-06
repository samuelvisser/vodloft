import {faIcon} from '../../icons/faIcon'
import LedgerModal, {formatLedgerDate} from '../common/LedgerModal'

import ProgressButton from '../common/ProgressButton'
import type {FrontendOperationDefinition} from '../../lib/operationDefinitions'
import {useTaskLedgerInfinite, type TaskLedgerCollectionQuery} from '../../lib/taskLedger'
import type {TaskLedgerEntryRead} from '../../types/schemas/task'

type Props = {
    open: boolean
    title: string
    definition: FrontendOperationDefinition
    query: Omit<TaskLedgerCollectionQuery, 'limit' | 'enabled'>
    starting: boolean
    canceling: boolean
    onClose: () => void
    onRunNow: () => void | Promise<void>
    onCancel: () => void | Promise<void>
}

const PAGE_SIZE = 25

function formatDuration(value: number | null | undefined): string {
    if (value == null || !Number.isFinite(value)) return '—'
    if (value < 1000) return `${Math.max(0, Math.round(value))} ms`

    const seconds = Math.max(0, Math.round(value / 1000))
    if (seconds < 60) return `${seconds} s`

    const minutes = Math.floor(seconds / 60)
    const remainingSeconds = seconds % 60
    if (minutes < 60) return remainingSeconds ? `${minutes}m ${remainingSeconds}s` : `${minutes}m`

    const hours = Math.floor(minutes / 60)
    const remainingMinutes = minutes % 60
    return remainingMinutes ? `${hours}h ${remainingMinutes}m` : `${hours}h`
}

function statusLabel(status: string): string {
    switch (status) {
        case 'SCHEDULED':
            return 'Scheduled'
        case 'QUEUED':
            return 'Queued'
        case 'RUNNING':
            return 'Running'
        case 'SUCCEEDED':
            return 'Succeeded'
        case 'FAILED':
            return 'Failed'
        case 'CANCELED':
            return 'Canceled'
        case 'RETRY_SCHEDULED':
            return 'Retry scheduled'
        default:
            return status.replace(/_/g, ' ').toLowerCase().replace(/^./, (character) => character.toUpperCase())
    }
}

function targetLabel(entry: TaskLedgerEntryRead, query: Props['query']): string | null {
    if (query.resourceId !== undefined || entry.resourceId == null) return null

    const type = entry.resourceType.replace(/_/g, ' ')
    const label = type.replace(/^./, (character) => character.toUpperCase())
    return `${label} ${entry.resourceId}`
}

function statusDetail(entry: TaskLedgerEntryRead): string | null {
    if (entry.status === 'FAILED' && entry.lastError) return entry.lastError
    if (entry.message && entry.message !== statusLabel(entry.status)) return entry.message
    return null
}

export default function CronTaskLedgerModal({
    open,
    title,
    definition,
    query,
    starting,
    canceling,
    onClose,
    onRunNow,
    onCancel,
}: Props) {
    const ledger = useTaskLedgerInfinite({
        ...query,
        orderBy: query.orderBy ?? 'created_at',
        order: query.order ?? 'desc',
        limit: PAGE_SIZE,
        enabled: open,
    })

    return (
        <LedgerModal<TaskLedgerEntryRead>
            open={open}
            title={`${title} log`}
            subtitle="Task ledger"
            icon={faIcon('fass', 'file-lines')}
            noun="runs"
            tableLabel={`${title} task history`}
            pages={ledger}
            gridColumns="minmax(0, 1fr) 160px 82px"
            rowKey={(entry) => entry.id}
            columns={[
                {header: 'Ran', cell: (entry) => formatLedgerDate(entry.startedAt ?? entry.finishedAt)},
                {
                    header: 'Result',
                    cell: (entry) => {
                        const target = targetLabel(entry, query)
                        return (
                            <span className="ledger-modal__detail" title={statusDetail(entry) ?? undefined}>
                                <span className={`is-${entry.status.toLowerCase()}`}>{statusLabel(entry.status)}</span>
                                {target ? <small>{target}</small> : null}
                            </span>
                        )
                    },
                },
                {header: 'Duration', cell: (entry) => formatDuration(entry.runtimeMs), wideOnly: true},
            ]}
            onClose={onClose}
            actions={
                <ProgressButton
                    definition={definition}
                    resourceId={0}
                    label="Run now"
                    icon={faIcon('fass', 'play')}
                    onClick={() => void onRunNow()}
                    starting={starting}
                    onCancel={() => void onCancel()}
                    cancelDisabled={canceling}
                    cancelLabel={`Cancel ${definition.label}`}
                />
            }
        />
    )
}
