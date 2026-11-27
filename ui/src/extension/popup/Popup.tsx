import {FormEvent, useEffect, useMemo, useState} from 'react'
import {useQuery} from '@tanstack/react-query'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import {can, loadAccess} from '../../lib/access'
import {apiJson} from '../../lib/api'
import type {QuickDownloadSettingsForUser} from '../../lib/quickDownloads'
import {
    ext, isWebPage, messageOf, normalAddress, storeAddress, storedAddress, unreachable, connectTo, vodloftOrigins,
} from '../browser'
import {ALL_SITES, sendCookies} from '../cookies'
import ActionMenu, {type ActionMenuItem} from '../../components/ActionMenu/ActionMenu'
import PageMedia from './PageMedia'
import QueueList from './QueueList'
import QuickDownloadForm, {choicesWithoutVodloft} from './QuickDownloadForm'

type Tab = {id: number; url?: string; title?: string; favIconUrl?: string; cookieStoreId?: string}
/** How VODLoft answers: signed in, signed out, or not at all. */
type Connection = 'checking' | 'signed-in' | 'sign-in' | 'vodloft'

const SETTINGS_KEY = 'quickSettings'

async function currentTab(): Promise<Tab | undefined> {
    const [tab] = await ext.tabs.query({active: true, currentWindow: true})
    return tab
}

/** Where the user's VODLoft is, asked once, with access to it. */
function Setup({current, tab, onSaved, onCancel}: {
    current: string | null; tab: Tab | undefined; onSaved: (address: string) => void; onCancel?: () => void
}) {
    // The tab may show VODLoft itself, which is the address to keep.
    const guess = current ?? (isWebPage(tab?.url) && /vodloft/i.test(tab?.title ?? '') ? new URL(tab!.url!).origin : '')
    const [typed, setTyped] = useState(guess)
    const [problem, setProblem] = useState<string | null>(null)

    const submit = async (event: FormEvent) => {
        event.preventDefault()
        setProblem(null)
        let address: string
        try {
            address = normalAddress(typed)
        } catch {
            setProblem('Type the address you open VODLoft on, such as https://vodloft.example.com')
            return
        }
        // Asked before anything else is awaited: browsers only ask for permissions right on a click. Firefox may
        // close this popup to ask, so the address is saved meanwhile.
        const asking = ext.permissions.request(vodloftOrigins(address))
        await storeAddress(address)
        if (!await asking.catch(() => false)) {
            setProblem('The extension can only reach VODLoft once you allow it.')
            return
        }
        onSaved(address)
    }

    return (
        <form className="extension-setup" onSubmit={(event) => void submit(event)}>
            <p>Add what you find on the web to your own VODLoft, or quick download it, right from the page you are on.</p>
            <label className="form-label" htmlFor="address">Your VODLoft address</label>
            <input id="address" className="input" type="url" placeholder="https://vodloft.example.com" autoComplete="url"
                   required autoFocus value={typed} onChange={(event) => setTyped(event.target.value)}/>
            {problem && <p className="form-error" role="alert">{problem}</p>}
            <p className="help">Your browser asks you to let the extension reach this address. Stay signed in to VODLoft in
                this browser: the extension works as you.</p>
            <div className="actions">
                <button type="submit" className="btn btn-primary">Save</button>
                {onCancel && <button type="button" className="btn" onClick={onCancel}>Cancel</button>}
            </div>
        </form>
    )
}

/** The page while VODLoft does not answer, or wants the user to sign in: a download can still be chosen and waits. */
function Unanswered({address, tab, reason, settings}: {
    address: string; tab: Tab; reason: 'vodloft' | 'sign-in'; settings: QuickDownloadSettingsForUser | undefined
}) {
    const [quickOpen, setQuickOpen] = useState(false)
    const options = useMemo(choicesWithoutVodloft, [])
    const title = tab.title || new URL(tab.url!).hostname
    return (
        <>
            <div className={reason === 'vodloft' ? 'form-error-card extension-problem' : 'extension-problem extension-problem--quiet'} role="alert">
                {reason === 'vodloft'
                    ? <>VODLoft does not answer at <strong>{address}</strong>. It may be down or restarting.</>
                    : <>Sign in to VODLoft in this browser, then open the extension again.</>}
                {reason === 'sign-in' && (
                    <div className="actions">
                        <a className="btn btn-primary" href={address} target="_blank" rel="noreferrer">Open VODLoft to sign in</a>
                    </div>
                )}
            </div>
            <article className="add-media-preview extension-page" aria-label="This page">
                <div className="add-media-preview-copy">
                    <p>{new URL(tab.url!).hostname.replace(/^www\./, '')}</p>
                    <h2>{title}</h2>
                    <div className="add-media-preview-actions">
                        <button className={`btn${quickOpen ? ' is-active' : ''}`} type="button" aria-expanded={quickOpen}
                                onClick={() => setQuickOpen((open) => !open)} title="Download the file without adding it to your library">
                            <FontAwesomeIcon icon={faIcon('fass', 'bolt')}/>
                            Quick download
                        </button>
                    </div>
                </div>
            </article>
            {quickOpen && (
                <QuickDownloadForm url={tab.url!} sourceKey={null} title={title} imageUrl={null} options={options}
                                   settings={settings} waiting={reason} onQueued={() => setQuickOpen(false)}/>
            )}
        </>
    )
}

type CookieResult = {tone: 'ok' | 'problem'; text: string}

/** The extension's other tool: the cookies of the page's site, for VODLoft to sign in there with. */
function useCookieSending(tab: Tab | undefined) {
    const [sending, setSending] = useState(false)
    const [result, setResult] = useState<CookieResult | null>(null)
    const send = async () => {
        if (!tab) return
        // Asked right on the click, before anything is awaited, as browsers require.
        const asking = ext.permissions.request(ALL_SITES)
        setSending(true)
        setResult(null)
        try {
            if (!await asking.catch(() => false)) {
                setResult({tone: 'problem', text: 'The extension can only send cookies once you allow it to read them.'})
                return
            }
            setResult(await sendCookies({id: tab.id, url: tab.url!, cookieStoreId: tab.cookieStoreId}))
        } catch (exc) {
            setResult({tone: 'problem', text: messageOf(exc)})
        } finally {
            setSending(false)
        }
    }
    return {send, sending, result}
}

export default function Popup() {
    const [address, setAddress] = useState<string | null | undefined>(undefined)
    const [tab, setTab] = useState<Tab | undefined>(undefined)
    const [changing, setChanging] = useState(false)
    const [connection, setConnection] = useState<Connection>('checking')
    const [cachedSettings, setCachedSettings] = useState<QuickDownloadSettingsForUser | undefined>(undefined)

    useEffect(() => {
        void Promise.all([storedAddress(), currentTab(), ext.storage.local.get(SETTINGS_KEY)]).then(([stored, current, cached]) => {
            setTab(current)
            setCachedSettings(cached?.[SETTINGS_KEY])
            setAddress(stored)
        })
    }, [])

    useEffect(() => {
        if (!address || changing) return
        connectTo(address)
        setConnection('checking')
        let stale = false
        ext.permissions.contains(vodloftOrigins(address)).then(async (allowed: boolean) => {
            if (!allowed) {
                if (!stale) setChanging(true)
                return
            }
            try {
                const access = await loadAccess()
                if (!stale) setConnection(access ? 'signed-in' : 'sign-in')
            } catch (exc) {
                if (!stale) setConnection(unreachable(exc) ? 'vodloft' : 'sign-in')
            }
        })
        return () => { stale = true }
    }, [address, changing])

    // Settings › Quick download, kept for a download chosen while VODLoft does not answer.
    const {data: liveSettings} = useQuery({
        queryKey: ['quickDownloadSettings', address],
        enabled: connection === 'signed-in' && can('quick_downloads'),
        queryFn: () => apiJson('/quick-downloads/settings', (data) => data as QuickDownloadSettingsForUser),
        staleTime: 60_000,
    })
    useEffect(() => {
        if (liveSettings) void ext.storage.local.set({[SETTINGS_KEY]: liveSettings})
    }, [liveSettings])
    const settings = liveSettings ?? cachedSettings
    const page = isWebPage(tab?.url) ? tab : undefined
    const cookies = useCookieSending(page)

    if (address === undefined) return null
    if (!address || changing) {
        return (
            <Shell address={null}>
                <Setup current={address} tab={tab} onCancel={address ? () => setChanging(false) : undefined}
                       onSaved={(saved) => { setChanging(false); setAddress(saved) }}/>
            </Shell>
        )
    }

    // VODLoft's Actions menu, as on its own pages: open VODLoft, and send the page's cookies for those who may.
    const actions: ActionMenuItem[] = [
        {label: 'Open VODLoft', icon: faIcon('fass', 'arrow-up-right-from-square'), onSelect: () => openVodloft(address)},
    ]
    if (page && connection === 'signed-in' && can('sources', 'manage')) {
        actions.push({
            label: cookies.sending ? 'Sending cookies…' : 'Send cookies to VODLoft',
            description: `For ${new URL(page.url!).hostname.replace(/^www\./, '')}, to download what your account there can see`,
            icon: faIcon('fass', 'cookie-bite'),
            disabled: cookies.sending,
            onSelect: () => void cookies.send(),
        })
    }
    return (
        <Shell address={address} actions={actions} onChange={() => setChanging(true)}>
            {cookies.result && (
                <p className={cookies.result.tone === 'ok' ? 'extension-result quick-ok' : 'form-error-card extension-problem'} role="status">
                    {cookies.result.text}
                </p>
            )}
            {!page ? (
                <p className="extension-note">
                    Open the page of a video, a movie or a collection, such as a YouTube video or channel, and click the
                    VODLoft icon to add it.
                </p>
            ) : connection === 'checking' ? (
                <article className="add-media-preview add-media-preview--loading creator-skeleton" aria-busy="true" aria-label="Reaching VODLoft">
                    <span className="add-media-preview-art skeleton-block" aria-hidden="true"/>
                </article>
            ) : connection === 'signed-in' ? (
                <PageMedia address={address} pageUrl={page.url!} settings={settings} onLost={setConnection}/>
            ) : (
                <Unanswered address={address} tab={page} reason={connection} settings={settings}/>
            )}
            <QueueList/>
        </Shell>
    )
}

function openVodloft(address: string) {
    void ext.tabs.create({url: address})
    window.close()
}

function Shell({address, actions, onChange, children}: {
    address: string | null; actions?: ActionMenuItem[]; onChange?: () => void; children: React.ReactNode
}) {
    return (
        <main className="extension-popup">
            <header className="extension-header">
                <img src="icons/icon-32.png" alt="" width="24" height="24"/>
                <h1>VODLoft</h1>
                {actions && <ActionMenu items={actions} className="extension-actions"/>}
            </header>
            {children}
            {address && (
                <footer className="extension-footer">
                    <span>{address}</span>
                    <button type="button" className="quick-link-button" onClick={onChange}>Change</button>
                </footer>
            )}
        </main>
    )
}
