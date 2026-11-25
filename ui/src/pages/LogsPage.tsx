import {memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import Switch from 'react-switch'
import {faIcon} from '../icons/faIcon'
import {ClearInputButton} from '../components/common/ClearInputButton'

import PageSubtitle from '../components/common/PageSubtitle'
import SimpleSelect from '../components/common/SimpleSelect'
import {usePageActive} from '../lib/pageActivity'
import {
    ApplicationLogPageReadSchema,
    type ApplicationLogEntryRead,
    type ApplicationLogPageRead,
} from '../types/schemas/log'
import {createSelectRegistry} from '../utils/selectRegistry'
import './LogsPage.css'
import {apiUrl} from '../lib/api'

// Each level shows itself and every more severe level.
const LogLevelReg = createSelectRegistry('LogLevelFilter', {
    DEBUG: {label: 'Debug'},
    INFO: {label: 'Info'},
    WARNING: {label: 'Warning'},
    ERROR: {label: 'Error'},
    CRITICAL: {label: 'Critical'},
})

// The log is read a page at a time: the newest records first, older ones while the user scrolls up, and new
// ones as they arrive. Fetching and drawing all 20,000 retained records every poll froze the browser.
const PAGE_SIZE = 500
const POLL_MS = 2000
// Start loading the previous page this close to the top, so scrolling up rarely has to wait.
const LOAD_OLDER_MARGIN = 400

type LogWindow = {
    items: ApplicationLogEntryRead[]
    total: number
    level: ApplicationLogPageRead['level']
    hasOlder: boolean
}

async function fetchLogPage(
    filters: string,
    position: {before?: number, after?: number},
    signal?: AbortSignal,
): Promise<ApplicationLogPageRead> {
    const query = new URLSearchParams(filters)
    query.set('limit', String(PAGE_SIZE))
    if (position.before !== undefined) query.set('before', String(position.before))
    if (position.after !== undefined) query.set('after', String(position.after))
    const response = await fetch(`${apiUrl()}/logs?${query}`, {signal, credentials: 'include'})
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    return ApplicationLogPageReadSchema.parse(await response.json())
}

function formatTimestamp(value: string): string {
    const date = new Date(value)
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

const LogEntryRow = memo(function LogEntryRow({entry}: {entry: ApplicationLogEntryRead}) {
    return (
        <div className="log-entry">
            <time>{formatTimestamp(entry.timestamp)}</time>
            <strong className={`log-level is-${entry.level.toLowerCase()}`}>{entry.level}</strong>
            <span className="log-logger">[{entry.logger}]</span>
            <span className="log-message">
                {entry.message}
                {entry.exception && <pre>{entry.exception}</pre>}
            </span>
        </div>
    )
})

export default function LogsPage() {
    // Until the user picks one, the server shows the level configured in the log settings.
    const [level, setLevel] = useState<string | null>(null)
    const [search, setSearch] = useState('')
    const [hidePullRequests, setHidePullRequests] = useState(true)
    const pageActive = usePageActive()
    const panelRef = useRef<HTMLDivElement | null>(null)
    const stickToBottomRef = useRef(true)
    // The scroll height before older records were put on top, to keep the same records in view.
    const heightBeforeOlderRef = useRef<number | null>(null)

    const [logWindow, setLogWindow] = useState<LogWindow | null>(null)
    const windowRef = useRef<LogWindow | null>(null)
    const [error, setError] = useState<string | null>(null)
    const [loadingOlder, setLoadingOlder] = useState(false)
    const loadingOlderRef = useRef(false)

    const filters = useMemo(() => {
        const query = new URLSearchParams()
        if (level) query.set('level', level)
        if (search.trim()) query.set('search', search.trim())
        if (hidePullRequests) query.set('hidePullRequests', 'true')
        return query.toString()
    }, [level, search, hidePullRequests])
    const filtersRef = useRef(filters)

    const updateWindow = useCallback((change: (current: LogWindow | null) => LogWindow | null) => {
        windowRef.current = change(windowRef.current)
        setLogWindow(windowRef.current)
    }, [])

    // New filters start again from the newest page.
    if (filtersRef.current !== filters) {
        filtersRef.current = filters
        windowRef.current = null
        stickToBottomRef.current = true
        setLogWindow(null)
        setError(null)
    }

    // Load the newest page, then keep adding what comes in after the last record shown. A page the user is not
    // looking at, such as in a window without focus, still shows the newest page, and waits to look for more.
    useEffect(() => {
        if (!pageActive && windowRef.current !== null) return
        const controller = new AbortController()
        let timer: ReturnType<typeof setTimeout> | undefined
        const poll = async () => {
            let delay = POLL_MS
            try {
                const shown = windowRef.current?.items ?? []
                const lastId = shown.length ? shown[shown.length - 1].id : undefined
                const page = await fetchLogPage(
                    filters,
                    lastId === undefined ? {} : {after: lastId},
                    controller.signal,
                )
                if (controller.signal.aborted) return
                updateWindow((current) => current === null || lastId === undefined
                    ? {items: page.items, total: page.total, level: page.level, hasOlder: page.hasOlder}
                    : {...current, items: [...current.items, ...page.items], total: page.total})
                setError(null)
                if (page.hasNewer) delay = 0
            } catch (caught) {
                if (controller.signal.aborted) return
                setError(caught instanceof Error ? caught.message : 'Could not load logs.')
            }
            if (pageActive || windowRef.current === null) timer = setTimeout(poll, delay)
        }
        void poll()
        return () => {
            controller.abort()
            clearTimeout(timer)
        }
    }, [filters, pageActive, updateWindow])

    const loadOlder = useCallback(async () => {
        const firstId = windowRef.current?.items[0]?.id
        if (firstId === undefined || !windowRef.current?.hasOlder || loadingOlderRef.current) return
        const requestFilters = filters
        loadingOlderRef.current = true
        setLoadingOlder(true)
        try {
            const page = await fetchLogPage(requestFilters, {before: firstId})
            if (filtersRef.current !== requestFilters) return
            heightBeforeOlderRef.current = panelRef.current?.scrollHeight ?? null
            updateWindow((current) => current && {
                ...current,
                items: [...page.items, ...current.items],
                hasOlder: page.hasOlder,
            })
        } catch (caught) {
            setError(caught instanceof Error ? caught.message : 'Could not load older logs.')
        } finally {
            loadingOlderRef.current = false
            setLoadingOlder(false)
        }
    }, [filters, updateWindow])

    const items = logWindow?.items ?? []
    const total = logWindow?.total ?? 0
    const shownLevel = level ?? logWindow?.level ?? null
    // Pull requests are logged at Info, so the switch only matters from Info down.
    const canShowPullRequests = shownLevel === 'DEBUG' || shownLevel === 'INFO'

    useLayoutEffect(() => {
        const panel = panelRef.current
        if (!panel) return
        if (heightBeforeOlderRef.current !== null) {
            panel.scrollTop += panel.scrollHeight - heightBeforeOlderRef.current
            heightBeforeOlderRef.current = null
        } else if (stickToBottomRef.current) {
            panel.scrollTop = panel.scrollHeight
        }
    }, [items])

    return (
        <section className="view logs-view" aria-labelledby="logs-title">
            <div className="view-header">
                <h1 id="logs-title">Log</h1>
                <PageSubtitle summary={<>Application-wide VODLoft log output.</>}>
                    <p>
                        Logs from the backend, scheduler, task workers, downloads and web server are collected here.
                        The latest 20,000 records from the current server process are retained. The newest are shown
                        first; scroll up to load older ones. A level shows its own records and every more severe
                        one, and the page opens at the level set in the log settings. Very long messages are cut
                        short here.
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
                        value={shownLevel}
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
                <strong className="logs-count">{total.toLocaleString()} {total === 1 ? 'entry' : 'entries'}</strong>
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
                    if (panel.scrollTop < LOAD_OLDER_MARGIN) void loadOlder()
                }}
            >
                {logWindow === null && error === null ? (
                    <div className="logs-message">
                        <FontAwesomeIcon className="vl-progress-icon" icon={faIcon('fass', 'spinner')}/>
                        Loading logs...
                    </div>
                ) : logWindow === null || (error !== null && items.length === 0) ? (
                    <div className="logs-message is-error">{error}</div>
                ) : items.length === 0 ? (
                    <div className="logs-message">No log entries match the current filters.</div>
                ) : (
                    <>
                        {logWindow.hasOlder && (
                            <div className="logs-message is-older">
                                {loadingOlder && (
                                    <FontAwesomeIcon className="vl-progress-icon" icon={faIcon('fass', 'spinner')}/>
                                )}
                                {loadingOlder ? 'Loading older logs...' : 'Scroll up for older logs'}
                            </div>
                        )}
                        {items.map((entry) => <LogEntryRow key={entry.id} entry={entry}/>)}
                    </>
                )}
            </div>
        </section>
    )
}
