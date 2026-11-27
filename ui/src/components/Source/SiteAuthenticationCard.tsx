import {ChangeEvent, useRef, useState} from 'react'
import {useQueryClient} from '@tanstack/react-query'
import {useForm} from 'react-hook-form'
import {z} from 'zod'
import {zodResolver} from '@hookform/resolvers/zod'

import {saveSiteCookies, useSiteAuthentication, useSourceApi} from '../../lib/queries'
import {apiFetch} from '../../lib/api'
import BrowserExtensionSteps from '../BrowserExtension/BrowserExtensionSteps'
import {SiteAuthenticationReadSchema, type SiteAuthenticationRead} from '../../types/schemas/source'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'
import SourceSection from './SourceSection'
import {sourceComponents} from './sourceComponents'
import AddSiteByLink from '../Settings/AddSiteByLink'
import SiteApiSettings from './SiteApiSettings'
import SiteAccountSettings from './SiteAccountSettings'
import SiteRow, {SiteBadge, SiteRows} from '../Settings/SiteRow'
import './SiteAuthenticationCard.css'

const errorText = (exc: unknown) => exc instanceof Error ? exc.message : String(exc)

/** A hidden file input with the button that opens it, for a cookies.txt file. */
function CookiesFileButton({label, ariaLabel, disabled, onFile}: {
    label: string
    ariaLabel: string
    disabled: boolean
    onFile: (content: string) => void
}) {
    const inputRef = useRef<HTMLInputElement | null>(null)
    const choose = async (event: ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0]
        event.target.value = ''
        if (file) onFile(await file.text())
    }
    return (
        <>
            <input
                ref={inputRef} className="sr-only" type="file" accept=".txt,text/plain" aria-label={ariaLabel}
                onChange={(event) => void choose(event)}
            />
            <button className="btn" type="button" onClick={() => inputRef.current?.click()} disabled={disabled}>
                {label}
            </button>
        </>
    )
}

/** How to send a site's cookies with VODLoft's browser extension. */
function CookieExtensionSteps({site}: {site: SiteAuthenticationRead}) {
    return (
        <BrowserExtensionSteps summary="Optional: Send cookies from your browser" className="site-cookies-extension">
            <li>
                <span>
                    Open a page of {site.name} while you are signed in there, click the VODLoft icon, open Actions and
                    choose Send cookies to VODLoft. Your browser asks you once to let the extension read sites&apos; cookies.
                </span>
            </li>
        </BrowserExtensionSteps>
    )
}

const sitesNamed = (names: string[]) => names.length <= 1
    ? names.join('')
    : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`

function cookieCount(count: number) {
    return `${count} ${count === 1 ? 'cookie' : 'cookies'}`
}

const PastedCookiesSchema = z.object({
    content: z.string().trim().min(1, 'Paste the cookies here first').default(''),
})
type PastedCookiesIn = z.input<typeof PastedCookiesSchema>
type PastedCookies = z.output<typeof PastedCookiesSchema>

/** Cookies pasted as the text of a cookies.txt file, for when saving them as a file first is a detour. */
function PasteCookiesForm({site, onSaved, onClose}: {
    site: SiteAuthenticationRead
    onSaved: (site: SiteAuthenticationRead) => void
    onClose: () => void
}) {
    const form = useForm<PastedCookiesIn, unknown, PastedCookies>({resolver: zodResolver(PastedCookiesSchema), defaultValues: PastedCookiesSchema.parse({})})
    const {register, formState: {errors, isSubmitting}} = form
    const onSubmit = buildServerAwareSubmit<PastedCookiesIn, PastedCookies, SiteAuthenticationRead>(
        form,
        async (data) => apiFetch(`/sources/authentication/${encodeURIComponent(site.key)}/cookies`, {
            method: 'PUT', json: {content: data.content},
        }),
        {
            fallbackField: 'content',
            parseSuccess: async (response) => SiteAuthenticationReadSchema.parse(await response.json()),
            onSuccess: async (listing) => {
                onSaved(listing)
                onClose()
            },
        },
    )
    return (
        <form className="site-cookies-paste" onSubmit={onSubmit} noValidate>
            <label className="site-api-form__field">
                <span>Cookies</span>
                <textarea
                    className="input site-cookies-paste__text" rows={6} spellCheck={false} autoComplete="off"
                    placeholder={'# Netscape HTTP Cookie File\n.example.com\tTRUE\t/\tTRUE\t0\tname\tvalue'}
                    aria-invalid={Boolean(errors.content)} {...register('content')}
                />
                {errors.content && <span className="error" role="alert">{String(errors.content.message)}</span>}
            </label>
            {errors.root && <div className="error" role="alert">{String(errors.root.message)}</div>}
            <div className="youtube-api-key">
                <button className="btn btn-primary" type="submit" disabled={isSubmitting}>
                    {isSubmitting ? 'Saving…' : 'Save cookies'}
                </button>
                <button className="btn" type="button" onClick={onClose} disabled={isSubmitting}>Cancel</button>
            </div>
        </form>
    )
}

/** The cookies file of one Site. */
function SiteCookies({site, onSaved}: {site: SiteAuthenticationRead; onSaved: (site: SiteAuthenticationRead) => void}) {
    const [saving, setSaving] = useState(false)
    const [pasting, setPasting] = useState(false)
    const [error, setError] = useState<string | null>(null)

    const save = async (content: string | null) => {
        setSaving(true)
        setError(null)
        try {
            onSaved(await saveSiteCookies(site.key, content))
        } catch (exc) {
            setError(errorText(exc))
        } finally {
            setSaving(false)
        }
    }

    const domain = site.domains[0]
    return (
        <div className="source-setting">
            <div className="source-setting-copy">
                <h4>
                    Cookies file{' '}
                    {site.cookiesStatus && (
                        <span className={`youtube-api-state ${site.cookiesStatus.ok ? 'is-ok' : 'is-problem'}`}>
                            {site.cookiesStatus.label}
                        </span>
                    )}
                </h4>
                <p>
                    {site.cookiesHelp ?? (
                        <>
                            For videos that are only available when you are signed in, such as age-restricted or
                            members-only videos. Export a cookies.txt file from a browser where you are signed in
                            {domain ? ` on ${domain}` : ''}, and choose it here.
                        </>
                    )}
                    {' '}{sitesNamed(site.cookieSourceNames)} {site.cookieSourceNames.length === 1 ? 'signs' : 'sign'} in with
                    it for every lookup and download on {site.name}.
                </p>
                <p>
                    You can also paste the cookies, or send them from your browser in one click with VODLoft&apos;s
                    browser extension.
                </p>
                <p>
                    {site.hasCookies
                        ? `The cookies file has ${cookieCount(site.cookieCount)} for ${site.name}.`
                        : `${site.name} has no cookies file.`}
                </p>
                {site.cookiesStatus?.detail && (
                    <p className={site.cookiesStatus.ok ? 'youtube-api-ok' : 'source-setting-error'}>{site.cookiesStatus.detail}</p>
                )}
                {error && <p className="source-setting-error" role="alert">{error}</p>}
                <CookieExtensionSteps site={site}/>
                {pasting && <PasteCookiesForm site={site} onSaved={onSaved} onClose={() => setPasting(false)}/>}
            </div>
            <div className="source-setting-actions">
                <CookiesFileButton
                    label={site.hasCookies ? 'Replace file' : 'Choose file'} ariaLabel={`Cookies file for ${site.name}`}
                    disabled={saving} onFile={(content) => void save(content)}
                />
                {!pasting && (
                    <button className="btn" type="button" onClick={() => setPasting(true)} disabled={saving}>
                        Paste cookies
                    </button>
                )}
                {site.hasCookies && (
                    <button className="btn" type="button" onClick={() => void save(null)} disabled={saving}>
                        Remove
                    </button>
                )}
            </div>
        </div>
    )
}

/** The API key's state on the Site, from the Source whose key it is. */
function useApiKeyBadge(sourceKey: string | null) {
    const {data: status} = useSourceApi(sourceKey ?? '', Boolean(sourceKey))
    if (!sourceKey || !status?.keyHint) return null
    return status.problem
        ? <SiteBadge key="api-key" tone="problem">API key not working</SiteBadge>
        : <SiteBadge key="api-key" tone="on">API key</SiteBadge>
}

function badges(site: SiteAuthenticationRead, apiKey: ReturnType<typeof useApiKeyBadge>) {
    const shown = []
    if (site.signInSourceKey) shown.push(<SiteBadge key="sign-in" tone="own">Own sign-in</SiteBadge>)
    if (site.accountStatus?.signedIn) {
        shown.push(site.accountStatus.problem
            ? <SiteBadge key="account" tone="problem">Sign-in not working</SiteBadge>
            : <SiteBadge key="account" tone="on">Signed in</SiteBadge>)
    }
    if (site.cookiesStatus) {
        shown.push(<SiteBadge key="status" tone={site.cookiesStatus.ok ? 'on' : 'problem'}>{site.cookiesStatus.label}</SiteBadge>)
    } else if (site.hasCookies) {
        shown.push(<SiteBadge key="cookies" tone="on">Cookies file</SiteBadge>)
    }
    if (apiKey) shown.push(apiKey)
    if (site.siteApiStatus?.setUp) {
        shown.push(site.siteApiStatus.problem
            ? <SiteBadge key="site-api" tone="problem">{`${site.siteApi?.name ?? 'API'} not working`}</SiteBadge>
            : <SiteBadge key="site-api" tone="on">{site.siteApi?.name ?? 'API'}</SiteBadge>)
    }
    if (!shown.length) shown.push(<SiteBadge key="none" tone="off">Not signed in</SiteBadge>)
    return shown
}

function SiteAuthenticationRow({site, onSaved, alone}: {
    site: SiteAuthenticationRead
    onSaved: (site: SiteAuthenticationRead) => void
    /** The only Site listed. */
    alone: boolean
}) {
    const {SignIn} = site.signInSourceKey ? sourceComponents(site.signInSourceKey) : {}
    const {ApiKey} = site.apiKeySourceKey ? sourceComponents(site.apiKeySourceKey) : {}
    const apiKeyBadge = useApiKeyBadge(ApiKey ? site.apiKeySourceKey : null)
    const takesCookies = site.cookieSourceNames.length > 0
    return (
        <SiteRow
            siteKey={site.key} name={site.name} domains={site.domains} badges={badges(site, apiKeyBadge)}
            removable={site.removable} alone={alone}
            bodyClassName="source-section__body site-authentication__body"
        >
            {SignIn ? <SignIn/> : null}
            {ApiKey ? <ApiKey/> : null}
            {site.accountSignIn ? <SiteAccountSettings site={site} onSaved={onSaved}/> : null}
            {site.siteApi ? <SiteApiSettings site={site} onSaved={onSaved}/> : null}
            {takesCookies ? <SiteCookies site={site} onSaved={onSaved}/> : null}
            {!SignIn && !ApiKey && !site.accountSignIn && !site.siteApi && !takesCookies ? <p className="settings-field__help">VODLoft can't sign in on {site.name}.</p> : null}
        </SiteRow>
    )
}

/** Every Site VODLoft knows, with how it signs in there: its own sign-in, its API key or its cookies file.
 *  ``addSites`` offers to add another Site by its address below them. */
export function SiteAuthentication({addSites = true}: {addSites?: boolean} = {}) {
    const queryClient = useQueryClient()
    const {data: sites, isLoading, error: loadError} = useSiteAuthentication()

    const saved = (site: SiteAuthenticationRead) => {
        queryClient.setQueryData<SiteAuthenticationRead[]>(['siteAuthentication'], (current) => {
            if (!current) return [site]
            return current.some((item) => item.key === site.key)
                ? current.map((item) => (item.key === site.key ? site : item))
                : [...current, site]
        })
        void queryClient.invalidateQueries({queryKey: ['siteAuthentication']})
        // Signing in or out can change what a Source's subscription allows.
        void queryClient.invalidateQueries({queryKey: ['sources']})
    }

    return (
        <>
            {isLoading && <p className="settings-field__help">Loading sites…</p>}
            {loadError && <p className="source-setting-error" role="alert">Could not load the sites: {loadError.message}</p>}
            {sites?.length ? (
                <SiteRows>
                    {sites.map((site) => <SiteAuthenticationRow key={site.key} site={site} onSaved={saved} alone={sites.length === 1}/>)}
                </SiteRows>
            ) : null}
            {addSites ? <AddSiteByLink/> : null}
        </>
    )
}

export default function SiteAuthenticationCard() {
    return (
        <SourceSection
            title="Authentication"
            description="Sign-ins, cookies files and API keys, per site. Only needed for content that requires an account, such as members-only videos, or to make a site faster."
        >
            <SiteAuthentication/>
        </SourceSection>
    )
}
