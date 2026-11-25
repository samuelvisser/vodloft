import {useQuery} from '@tanstack/react-query'
import {useEffect, useMemo, useRef, useState} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import Switch from 'react-switch'
import {faIcon} from '../icons/faIcon'
import {ClearInputButton} from '../components/common/ClearInputButton'

import PageSubtitle from '../components/common/PageSubtitle'
import SimpleSelect from '../components/common/SimpleSelect'
import {usePageActive} from '../lib/pageActivity'
import {ApplicationLogPageReadSchema} from '../types/schemas/log'
import {createSelectRegistry} from '../utils/selectRegistry'
import './LogsPage.css'
import {apiUrl} from '../lib/api'

const LogLevelReg = createSelectRegistry('LogLevelFilter', {
    '': {label: 'All'},
    DEBUG: {label: 'Debug'},
    INFO: {label: 'Info'},
    WARNING: {label: 'Warning'},
    ERROR: {label: 'Error'},
    CRITICAL: {label: 'Critical'},
})

// The page shows the newest records only: drawing all 20,000 retained records every poll froze the browser.
const SHOWN_LIMIT = 1000

function formatTimestamp(value: string): string {
    const date = new Date(value)
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

export default function LogsPage() {
    const [level, setLevel] = useState('')
    const [search, setSearch] = useState('')
    const [hidePullRequests, setHidePullRequests] = useState(true)
    const pageActive = usePageActive()
    const panelRef = useRef<HTMLDivElement | null>(null)
    const stickToBottomRef = useRef(true)

    const canShowPullRequests = level === '' || level === 'INFO'
    const hidePulls = canShowPullRequests && hidePullRequests
    const params = useMemo(() => {
        const query = new URLSearchParams({limit: String(SHOWN_LIMIT)})
        if (level) query.set('level', level)
        if (search.trim()) query.set('search', search.trim())
        if (hidePulls) query.set('hidePullRequests', 'true')
        return query.toString()
    }, [level, search, hidePulls])

    const logs = useQuery({
        queryKey: ['applicationLogs', level, search.trim(), hidePulls],
        queryFn: async ({signal}) => {
            const response = await fetch(
                `${apiUrl()}/logs?${params}`,
                {signal, credentials: 'include'},
            )
            if (!response.ok) throw new Error(`HTTP ${response.status}`)
            return ApplicationLogPageReadSchema.parse(await response.json())
        },
        enabled: pageActive,
        refetchInterval: 2000,
        refetchOnMount: 'always',
        refetchOnWindowFocus: false,
        refetchIntervalInBackground: false,
    })

    const items = useMemo(() => logs.data?.items ?? [], [logs.data?.items])
    const total = logs.data?.total ?? 0

    useEffect(() => {
        const panel = panelRef.current
        if (!panel || !stickToBottomRef.current) return
        panel.scrollTop = panel.scrollHeight
    }, [items])

    return (
        <section className="view logs-view" aria-labelledby="logs-title">
            <div className="view-header">
                <h1 id="logs-title">Log</h1>
                <PageSubtitle summary={<>Application-wide VODLoft log output.</>}>
                    <p>
                        Logs from the backend, scheduler, task workers, downloads and web server are collected here.
                        The latest 20,000 records from the current server process are retained, and the newest
                        1,000 that match the filters are shown. Very long messages are cut short here.
                    </p>
                </PageSubtitle>
            </div>

            <div className="logs-toolbar">
                <label className="logs-search has-clear-button">
                    <span className="sr-only">Search logs</span>
                    <FontAwesomeIcon icon={faIcon('fass', 'magnifying-glass')} aria-hidden="true"/>
                    <input
                        type="search"
                        value={search}
                        onChange={(event) => setSearch(event.target.value)}
                        placeholder="Search logs..."
                    />
                    {search && <ClearInputButton label="Clear the search" onClear={() => setSearch('')}/>}
                </label>
                <div className="logs-level">
                    <label htmlFor="logs-level-select">Level</label>
                    <SimpleSelect
                        inputId="logs-level-select"
                        className="logs-level-select"
                        registry={LogLevelReg}
                        value={level}
                        onChange={setLevel}
                    />
                </div>
                {canShowPullRequests && (
                    <div className="logs-pull-toggle">
                        <label id="logs-hide-pull-requests-label" htmlFor="logs-hide-pull-requests">Hide Pull requests</label>
                        <Switch
                            id="logs-hide-pull-requests"
                            checked={hidePullRequests}
                            onChange={setHidePullRequests}
                            onColor="#0ea5e9"
                            offColor="#94a3b8"
                            uncheckedIcon={false}
                            checkedIcon={false}
                            aria-labelledby="logs-hide-pull-requests-label"
                        />
                    </div>
                )}
                <strong className="logs-count">
                    {total > items.length && <>Newest {items.length.toLocaleString()} of </>}
                    {total.toLocaleString()} {total === 1 ? 'entry' : 'entries'}
                </strong>
            </div>

            <div
                ref={panelRef}
                className="logs-panel"
                role="log"
                aria-live="off"
                aria-label="Application logs"
                onScroll={(event) => {
                    const panel = event.currentTarget
                    stickToBottomRef.current = panel.scrollHeight - panel.scrollTop - panel.clientHeight < 80
                }}
            >
                {logs.isPending ? (
                    <div className="logs-message">
                        <FontAwesomeIcon className="vl-progress-icon" icon={faIcon('fass', 'spinner')}/>
                        Loading logs...
                    </div>
                ) : logs.error ? (
                    <div className="logs-message is-error">
                        {logs.error instanceof Error ? logs.error.message : 'Could not load logs.'}
                    </div>
                ) : items.length === 0 ? (
                    <div className="logs-message">No log entries match the current filters.</div>
                ) : (
                    items.map((entry) => (
                        <div className="log-entry" key={entry.id}>
                            <time>{formatTimestamp(entry.timestamp)}</time>
                            <strong className={`log-level is-${entry.level.toLowerCase()}`}>{entry.level}</strong>
                            <span className="log-logger">[{entry.logger}]</span>
                            <span className="log-message">
                                {entry.message}
                                {entry.exception && <pre>{entry.exception}</pre>}
                            </span>
                        </div>
                    ))
                )}
            </div>
        </section>
    )
}
