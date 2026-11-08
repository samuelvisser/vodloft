import {ChangeEvent, useRef, useState} from 'react'
import {useQueryClient} from '@tanstack/react-query'
import {useForm} from 'react-hook-form'
import {z} from 'zod'
import {zodResolver} from '@hookform/resolvers/zod'

import {apiUrl} from '../../lib/api'
import {saveSiteCookies, sortCookiesFile, useSiteSignIns} from '../../lib/queries'
import {SiteSignInReadSchema, type SiteSignInRead, type SortedCookiesRead} from '../../types/schemas/source'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'
import SourceSection from './SourceSection'
import {sourceComponents} from './sourceComponents'
import '../Settings/SiteSettingsCard.css'
import './SiteSignInsCard.css'

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

const sitesNamed = (names: string[]) => names.length <= 1
    ? names.join('')
    : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`

function cookieCount(count: number) {
    return `${count} ${count === 1 ? 'cookie' : 'cookies'}`
}

/** The cookies file of one Site. */
function SiteCookies({site, onSaved}: {site: SiteSignInRead; onSaved: (site: SiteSignInRead) => void}) {
    const [saving, setSaving] = useState(false)
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
                    {' '}{site.signInSourceKey
                        ? `${site.name}'s own sign-in above is all its own Source needs; ${sitesNamed(site.cookieSourceNames)} only uses this file when it fetches ${site.name}'s links.`
                        : `${sitesNamed(site.cookieSourceNames)} ${site.cookieSourceNames.length === 1 ? 'signs' : 'sign'} in with it for every lookup and download on ${site.name}.`}
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
            </div>
            <div className="source-setting-actions">
                <CookiesFileButton
                    label={site.hasCookies ? 'Replace file' : 'Choose file'} ariaLabel={`Cookies file for ${site.name}`}
                    disabled={saving} onFile={(content) => void save(content)}
                />
                {site.hasCookies && (
                    <button className="btn" type="button" onClick={() => void save(null)} disabled={saving}>
                        Remove
                    </button>
                )}
            </div>
        </div>
    )
}

function badges(site: SiteSignInRead) {
    const shown = []
    if (site.signInSourceKey) shown.push(<span key="sign-in" className="site-settings-badge site-settings-badge--own">Own sign-in</span>)
    if (site.cookiesStatus) {
        shown.push(
            <span key="status" className={`site-settings-badge ${site.cookiesStatus.ok ? 'site-settings-badge--on' : 'site-settings-badge--problem'}`}>
                {site.cookiesStatus.label}
            </span>,
        )
    } else if (site.hasCookies) {
        shown.push(<span key="cookies" className="site-settings-badge site-settings-badge--on">Cookies file</span>)
    }
    if (!shown.length) shown.push(<span key="none" className="site-settings-badge">Not signed in</span>)
    return shown
}

function SiteSignInRow({site, onSaved}: {site: SiteSignInRead; onSaved: (site: SiteSignInRead) => void}) {
    const {SignIn} = site.signInSourceKey ? sourceComponents(site.signInSourceKey) : {}
    const takesCookies = site.cookieSourceNames.length > 0
    return (
        <details className="site-settings-site site-sign-in">
            <summary>
                <span className="site-settings-site__name">
                    <strong>{site.name}</strong>
                    {site.domains.length ? <span>{site.domains.join(', ')}</span> : null}
                </span>
                <span className="site-settings-site__badges">{badges(site)}</span>
            </summary>
            <div className="site-settings-site__body source-section__body">
                {SignIn ? <SignIn/> : null}
                {takesCookies ? <SiteCookies site={site} onSaved={onSaved}/> : null}
                {!SignIn && !takesCookies ? <p className="settings-field__help">VODLoft can't sign in on {site.name}.</p> : null}
            </div>
        </details>
    )
}

function SortedResult({result}: {result: SortedCookiesRead}) {
    const names = result.sites.map((site) => `${site.name} (${cookieCount(site.cookieCount)})`)
    const other = result.otherDomains
    return (
        <div className="site-sign-ins-result" role="status">
            <p>
                {names.length
                    ? `The cookies file now signs in on ${sitesNamed(names)}.`
                    : 'The cookies file has no cookies for a Site VODLoft knows.'}
            </p>
            {other.length > 0 && (
                <p>
                    Left out the cookies of {other.length === 1 ? 'one other domain' : `${other.length} other domains`}:
                    {' '}{other.slice(0, 8).join(', ')}{other.length > 8 ? ', …' : ''}. To sign in on one of those sites,
                    add it below with a link to a channel or video there, and choose the file again.
                </p>
            )}
        </div>
    )
}

const AddSiteSchema = z.object({
    url: z.string().trim().min(1, 'Paste a link to a channel or video on the site').url('Paste a whole link, starting with https://'),
})
type AddSiteValues = z.input<typeof AddSiteSchema>

/** Add a Site by a link to it, before VODLoft has anything from it. */
function AddSiteForm({onAdded}: {onAdded: (site: SiteSignInRead) => void}) {
    const form = useForm<AddSiteValues>({
        resolver: zodResolver(AddSiteSchema),
        defaultValues: {url: ''},
    })
    const {register, formState: {errors, isSubmitting}} = form
    const onSubmit = buildServerAwareSubmit<AddSiteValues, AddSiteValues, SiteSignInRead>(
        form,
        async (data) => fetch(`${apiUrl()}/sources/sign-ins`, {
            method: 'POST',
            credentials: 'include',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({url: data.url.trim()}),
        }),
        {
            parseSuccess: async (response) => SiteSignInReadSchema.parse(await response.json()),
            onSuccess: (site, {resetForm}) => {
                resetForm({url: ''})
                onAdded(site)
            },
            fallbackField: 'url',
        },
    )
    return (
        <form className="source-setting site-sign-ins-add" onSubmit={onSubmit} noValidate>
            <div className="source-setting-copy">
                <h4>Another site</h4>
                <p>
                    A site shows up here once you add something from it. To sign in on a site first, such as Twitch
                    before adding a members-only channel, paste a link to a channel or video there.
                </p>
                <input
                    className="input settings-input" type="url" placeholder="https://www.twitch.tv/…"
                    aria-label="Link to a page on the site" aria-invalid={Boolean(errors.url)} {...register('url')}
                />
                {errors.url && <div className="error" role="alert">{String(errors.url.message)}</div>}
            </div>
            <div className="source-setting-actions">
                <button className="btn" type="submit" disabled={isSubmitting}>Add site</button>
            </div>
        </form>
    )
}

/** Every Site VODLoft knows, with its own sign-in and its cookies file, and one cookies file for several Sites. */
export function SiteSignIns() {
    const queryClient = useQueryClient()
    const {data: sites, isLoading, error: loadError} = useSiteSignIns()
    const [sorting, setSorting] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [result, setResult] = useState<SortedCookiesRead | null>(null)

    const refresh = async () => {
        await queryClient.invalidateQueries({queryKey: ['siteSignIns']})
        // Signing in or out can change what a Source's subscription allows.
        await queryClient.invalidateQueries({queryKey: ['sources']})
    }
    const saved = (site: SiteSignInRead) => {
        queryClient.setQueryData<SiteSignInRead[]>(['siteSignIns'], (current) => {
            if (!current) return [site]
            return current.some((item) => item.key === site.key)
                ? current.map((item) => (item.key === site.key ? site : item))
                : [...current, site]
        })
        void refresh()
    }
    const sort = async (content: string) => {
        setSorting(true)
        setError(null)
        setResult(null)
        try {
            setResult(await sortCookiesFile(content))
            await refresh()
        } catch (exc) {
            setError(errorText(exc))
        } finally {
            setSorting(false)
        }
    }

    return (
        <>
            <div className="source-setting">
                <div className="source-setting-copy">
                    <h4>One cookies file for several sites</h4>
                    <p>
                        Export a cookies.txt file from a browser where you are signed in on the sites you need, such as
                        YouTube and Twitch, and choose it here. Each site below gets the cookies for its own domains,
                        in place of the ones it had; a site without cookies in the file keeps its own.
                    </p>
                    {error && <p className="source-setting-error" role="alert">{error}</p>}
                </div>
                <div className="source-setting-actions">
                    <CookiesFileButton label="Choose file" ariaLabel="Cookies file for several sites" disabled={sorting} onFile={(content) => void sort(content)}/>
                </div>
            </div>
            {result && <SortedResult result={result}/>}
            {isLoading && <p className="settings-field__help">Loading sites…</p>}
            {loadError && <p className="source-setting-error" role="alert">Could not load the sites: {loadError.message}</p>}
            {sites?.length ? (
                <div className="site-settings-sites site-sign-ins-sites">
                    {sites.map((site) => <SiteSignInRow key={site.key} site={site} onSaved={saved}/>)}
                </div>
            ) : null}
            <AddSiteForm onAdded={saved}/>
        </>
    )
}

export default function SiteSignInsCard() {
    return (
        <SourceSection
            title="Sign-ins"
            description="Signing in is per site, and only needed for content that requires an account, such as members-only videos."
        >
            <SiteSignIns/>
        </SourceSection>
    )
}
