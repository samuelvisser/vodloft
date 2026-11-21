import type {IconProp} from '@fortawesome/fontawesome-svg-core'

/** One step of what an action does, as its details list them. */
export type ProgressStep = {
    id: string
    label: string
    state: 'pending' | 'running' | 'waiting' | 'completed' | 'skipped' | 'failed' | 'canceled'
    /** How far the running step is, or null while it cannot measure itself. */
    percent: number | null
}

export type ProgressPresentation = {
    mode: 'determinate' | 'indeterminate' | 'waiting' | 'terminal'
    active: boolean
    percent: number | null
    label: string
    compactLabel?: string
    detail: string
    icon: IconProp
    secondary?: string
    estimated?: boolean
    canCancel: boolean
    canRetry: boolean
    outcome?: 'success' | 'error' | 'canceled' | 'locked'
    /** The steps of the action's plan, when it has one. */
    steps?: ProgressStep[]
}

export type DownloadPresentation = ProgressPresentation & {status: string}
