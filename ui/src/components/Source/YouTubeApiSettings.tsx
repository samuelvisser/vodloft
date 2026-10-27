import {useState} from 'react'
import {useQueryClient} from '@tanstack/react-query'

import {ApiKeyRejectedError, changeSourceApiKey, useSourceApi} from '../../lib/queries'
import type {ApiStatusRead} from '../../types/schemas/source'
import type {SettingsTabProps} from '../Settings/SettingsTabTypes'
import {NumberField, SettingsSection} from '../Settings/SettingsControls'

const SOURCE_ID = 'ytdlp'
/** One search: the search call itself and one batch each of channel and video details. */
const SEARCH_UNITS = 102

const KEY_STEPS = [
    {
        text: 'Create a Google Cloud project. Any name works, such as "VODLoft".',
        button: 'Create project',
        url: 'https://console.cloud.google.com/projectcreate',
    },
    {
        text: 'Enable the YouTube Data API v3 in that project.',
        button: 'Enable the API',
        url: 'https://console.cloud.google.com/apis/library/youtube.googleapis.com',
    },
    {
        text: 'Create an API key under Credentials. Edit it, and under API restrictions restrict it to the YouTube Data API v3. Leave the other restrictions off.',
        button: 'Open Credentials',
        url: 'https://console.cloud.google.com/apis/credentials',
    },
]

function formatNumber(value: number): string {
    return value.toLocaleString()
}

/** How often each show can get a quick check from what the daily re-scan leaves of the checks share. */
function checkIntervalMinutes(showCount: number, rescanUnits: number, checksQuota: number, minInterval: number): number | null {
    if (showCount === 0) return minInterval
    const room = checksQuota - rescanUnits
    if (room <= 0) return null
    return Math.max(minInterval, Math.ceil((24 * 60) / (room / (showCount * 1.1))))
}

function formatInterval(minutes: number): string {
    if (minutes < 90) return `${minutes} min`
    const hours = Math.round(minutes / 60)
    return `${hours} hours`
}

function shareLine(status: ApiStatusRead): string {
    const share = (name: string) => status.shares.find((item) => item.name === name)
    const checks = share('checks')
    const search = share('search')
    const resets = new Date(status.resetsAt).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})
    return [
        checks ? `${formatNumber(checks.used)} of ${formatNumber(checks.limit)} for checks` : null,
        search ? `${formatNumber(search.used)} of ${formatNumber(search.limit)} for search` : null,
        `resets ${resets} your time`,
    ].filter(Boolean).join(' · ')
}

function ApiKeyPanel() {
    const queryClient = useQueryClient()
    const {data: status, error: loadError} = useSourceApi(SOURCE_ID)
    const [key, setKey] = useState('')
    const [busy, setBusy] = useState<'save' | 'test' | 'remove' | null>(null)
    const [error, setError] = useState<{message: string; fixUrl: string | null} | null>(null)
    const [tested, setTested] = useState(false)

    const run = async (action: 'save' | 'test' | 'remove') => {
        setBusy(action)
        setError(null)
        setTested(false)
        try {
            queryClient.setQueryData(['sourceApi', SOURCE_ID], await changeSourceApiKey(SOURCE_ID, action, key))
            void queryClient.invalidateQueries({queryKey: ['sourceProblems']})
            if (action === 'save') setKey('')
            if (action !== 'remove') setTested(true)
        } catch (exc) {
            setError({
                message: exc instanceof Error ? exc.message : String(exc),
                fixUrl: exc instanceof ApiKeyRejectedError ? exc.fixUrl : null,
            })
        } finally {
            setBusy(null)
        }
    }

    const hasKey = Boolean(status?.keyHint)
    const used = status?.shares.reduce((total, share) => total + share.used, 0) ?? 0
    const percent = status ? Math.min(100, Math.round((used / Math.max(status.dailyQuota, 1)) * 100)) : 0
    const problem = error ?? (status?.problem ? {message: status.problem, fixUrl: status.problemFixUrl} : null)

    return (
        <div className="source-setting youtube-api">
            <div className="source-setting-copy">
                <h4>
                    YouTube Data API{' '}
                    {hasKey && <span className={`youtube-api-state ${status?.problem ? 'is-problem' : 'is-ok'}`}>{status?.problem ? 'Not working' : 'Connected'}</span>}
                </h4>
                <p>
                    Optional. With a free API key, VODLoft lists YouTube channels and finds new videos much faster.
                    yt-dlp still downloads everything, and VODLoft works without a key.
                </p>
                {loadError && <p className="source-setting-error" role="alert">Could not load the API key status: {loadError.message}</p>}
                <form
                    className="youtube-api-key"
                    onSubmit={(event) => {
                        event.preventDefault()
                        if (key.trim()) void run('save')
                    }}
                >
                    <input
                        className="input"
                        type="password"
                        autoComplete="off"
                        aria-label="YouTube Data API key"
                        placeholder={hasKey ? `Key ending in ${status?.keyHint} — paste a new key to replace it` : 'Paste an API key'}
                        value={key}
                        onChange={(event) => setKey(event.target.value)}
                    />
                    <button className="btn btn-primary" type="submit" disabled={!key.trim() || busy !== null}>
                        {busy === 'save' ? 'Testing…' : 'Save and test'}
                    </button>
                    {hasKey && (
                        <button className="btn" type="button" onClick={() => void run('test')} disabled={busy !== null}>
                            {busy === 'test' ? 'Testing…' : 'Test key'}
                        </button>
                    )}
                    {hasKey && (
                        <button className="btn" type="button" onClick={() => void run('remove')} disabled={busy !== null}>
                            Remove
                        </button>
                    )}
                </form>
                {problem && (
                    <p className="source-setting-error" role="alert">
                        {problem.message}
                        {problem.fixUrl && <>{' '}<a href={problem.fixUrl} target="_blank" rel="noreferrer">Fix this in Google Cloud</a></>}
                    </p>
                )}
                {tested && !problem && <p className="youtube-api-ok" role="status">Google accepts this key.</p>}
                {status && hasKey && (
                    <div className="youtube-api-quota">
                        <div className="youtube-api-quota__line">
                            <span>Quota used today</span>
                            <span>{status.exhausted ? 'Used up according to Google · ' : ''}{shareLine(status)}</span>
                        </div>
                        <div className="youtube-api-meter" role="meter" aria-valuemin={0} aria-valuemax={status.dailyQuota} aria-valuenow={used} aria-label="Quota used today">
                            <span style={{width: `${status.exhausted ? 100 : percent}%`}}/>
                        </div>
                    </div>
                )}
                {!hasKey && (
                    <details className="youtube-api-guide">
                        <summary>Get a free key in about three minutes</summary>
                        <ol>
                            {KEY_STEPS.map((step) => (
                                <li key={step.url}>
                                    <span>{step.text}</span>
                                    <a className="btn" href={step.url} target="_blank" rel="noreferrer">{step.button}</a>
                                </li>
                            ))}
                            <li><span>Copy the key, paste it above and choose Save and test.</span></li>
                        </ol>
                        <p>
                            The key only reads public YouTube data. Google gives every project 10,000 units a day for
                            free, and VODLoft stays inside the split below.
                        </p>
                    </details>
                )}
            </div>
        </div>
    )
}

/** The yt-dlp Source's own settings: the optional YouTube Data API key and how to spend its quota. */
export default function YouTubeApiSettings({draft, updateDraft, environmentVariableFor, errorFor}: SettingsTabProps) {
    const {data: status} = useSourceApi(SOURCE_ID)
    const quota = draft.youtubeApi
    const keptFree = quota.dailyQuota - quota.checksQuota - quota.searchQuota
    const interval = status
        ? checkIntervalMinutes(status.showCount, status.rescanUnits, quota.checksQuota, quota.minCheckIntervalMinutes)
        : null
    const showCount = status?.showCount ?? 0
    const checksHelp = !status || showCount === 0
        ? 'Quick checks for new videos and the daily full re-scan of your YouTube shows.'
        : interval === null
            ? `Not enough for the daily re-scan of your ${showCount} YouTube shows (about ${formatNumber(status.rescanUnits)} units). Quick checks use RSS.`
            : `Quick check about every ${formatInterval(interval)} for your ${showCount} YouTube ${showCount === 1 ? 'show' : 'shows'}, plus the daily re-scan.`
    const searches = Number.isFinite(quota.searchQuota) ? Math.floor(quota.searchQuota / SEARCH_UNITS) : 0

    return (
        <>
            <ApiKeyPanel/>
            <SettingsSection
                className="youtube-api-split"
                defaultOpen={false}
                title="How to spend the YouTube API quota"
                description="Google does not tell an API key its limit, so VODLoft counts its own units and keeps to this split."
            >
                <NumberField
                    id="settings-youtube-daily-quota"
                    label="Daily total from Google"
                    value={quota.dailyQuota}
                    min={1}
                    step={1000}
                    unit="units"
                    error={errorFor('youtubeApi.dailyQuota')}
                    environmentVariable={environmentVariableFor('youtubeApi.dailyQuota')}
                    onChange={(value) => updateDraft((next) => {
                        next.youtubeApi.dailyQuota = value
                    })}
                    help="Google's default is 10,000. Only raise this if Google gave your project more."
                />
                <NumberField
                    id="settings-youtube-checks-quota"
                    label="Checks and re-scans"
                    value={quota.checksQuota}
                    step={500}
                    unit="units"
                    error={errorFor('youtubeApi.checksQuota')}
                    environmentVariable={environmentVariableFor('youtubeApi.checksQuota')}
                    onChange={(value) => updateDraft((next) => {
                        next.youtubeApi.checksQuota = value
                    })}
                    help={checksHelp}
                />
                <NumberField
                    id="settings-youtube-search-quota"
                    label="Search"
                    value={quota.searchQuota}
                    step={102}
                    unit="units"
                    error={errorFor('youtubeApi.searchQuota')}
                    environmentVariable={environmentVariableFor('youtubeApi.searchQuota')}
                    onChange={(value) => updateDraft((next) => {
                        next.youtubeApi.searchQuota = value
                    })}
                    help={searches > 0
                        ? `About ${searches} API ${searches === 1 ? 'search' : 'searches'} a day, then searches use yt-dlp.`
                        : 'Every search uses yt-dlp.'}
                />
                <NumberField
                    id="settings-youtube-min-check-interval"
                    label="Shortest check interval"
                    value={quota.minCheckIntervalMinutes}
                    min={10}
                    unit="minutes"
                    error={errorFor('youtubeApi.minCheckIntervalMinutes')}
                    environmentVariable={environmentVariableFor('youtubeApi.minCheckIntervalMinutes')}
                    onChange={(value) => updateDraft((next) => {
                        next.youtubeApi.minCheckIntervalMinutes = value
                    })}
                    help="VODLoft never checks a show more often than this, even with quota to spare."
                />
                <div className="settings-field">
                    <span className="youtube-api-split__label">Kept free</span>
                    <div className="youtube-api-split__value">{Number.isFinite(keptFree) ? `${formatNumber(Math.max(keptFree, 0))} units` : '—'}</div>
                    <div className="settings-field__help">For adding shows, Test key and manual refreshes.</div>
                </div>
            </SettingsSection>
        </>
    )
}
