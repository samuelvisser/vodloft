import {ChangeEvent, useRef, useState} from 'react'
import {useQueryClient} from '@tanstack/react-query'

import {saveSiteCookies, useSiteSignIns} from '../../lib/queries'
import type {SiteSignInRead} from '../../types/schemas/source'
import SourceSection from './SourceSection'
import {sourceComponents} from './sourceComponents'
import AddSiteByLink from '../Settings/AddSiteByLink'
import SiteRow, {SiteBadge, SiteRows} from '../Settings/SiteRow'
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
                    {' '}{sitesNamed(site.cookieSourceNames)} {site.cookieSourceNames.length === 1 ? 'signs' : 'sign'} in with
                    it for every lookup and download on {site.name}.
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
    if (site.signInSourceKey) shown.push(<SiteBadge key="sign-in" tone="own">Own sign-in</SiteBadge>)
    if (site.cookiesStatus) {
        shown.push(<SiteBadge key="status" tone={site.cookiesStatus.ok ? 'on' : 'problem'}>{site.cookiesStatus.label}</SiteBadge>)
    } else if (site.hasCookies) {
        shown.push(<SiteBadge key="cookies" tone="on">Cookies file</SiteBadge>)
    }
    if (!shown.length) shown.push(<SiteBadge key="none" tone="off">Not signed in</SiteBadge>)
    return shown
}

function SiteSignInRow({site, onSaved}: {site: SiteSignInRead; onSaved: (site: SiteSignInRead) => void}) {
    const {SignIn} = site.signInSourceKey ? sourceComponents(site.signInSourceKey) : {}
    const takesCookies = site.cookieSourceNames.length > 0
    return (
        <SiteRow name={site.name} domains={site.domains} badges={badges(site)} bodyClassName="source-section__body site-sign-in__body">
            {SignIn ? <SignIn/> : null}
            {takesCookies ? <SiteCookies site={site} onSaved={onSaved}/> : null}
            {!SignIn && !takesCookies ? <p className="settings-field__help">VODLoft can't sign in on {site.name}.</p> : null}
        </SiteRow>
    )
}

/** Every Site VODLoft knows, with its own sign-in or its cookies file. */
export function SiteSignIns() {
    const queryClient = useQueryClient()
    const {data: sites, isLoading, error: loadError} = useSiteSignIns()

    const saved = (site: SiteSignInRead) => {
        queryClient.setQueryData<SiteSignInRead[]>(['siteSignIns'], (current) => {
            if (!current) return [site]
            return current.some((item) => item.key === site.key)
                ? current.map((item) => (item.key === site.key ? site : item))
                : [...current, site]
        })
        void queryClient.invalidateQueries({queryKey: ['siteSignIns']})
        // Signing in or out can change what a Source's subscription allows.
        void queryClient.invalidateQueries({queryKey: ['sources']})
    }

    return (
        <>
            {isLoading && <p className="settings-field__help">Loading sites…</p>}
            {loadError && <p className="source-setting-error" role="alert">Could not load the sites: {loadError.message}</p>}
            {sites?.length ? (
                <SiteRows>
                    {sites.map((site) => <SiteSignInRow key={site.key} site={site} onSaved={saved}/>)}
                </SiteRows>
            ) : null}
            <AddSiteByLink/>
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
