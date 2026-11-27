import {useEffect, useState} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {useQueryClient} from '@tanstack/react-query'

import {faIcon} from '../../icons/faIcon'
import {apiUrl} from '../../lib/api'
import {useSiteChoices} from '../../lib/queries'
import type {SiteChoiceRead} from '../../types/schemas/source'
import {getErrorMessageFromResponse} from '../../utils/helpers'
import SiteIcon from '../common/SiteIcon'
import AddSiteByLink from '../Settings/AddSiteByLink'

type Props = {
    onBack: () => void
    onContinue: () => void
}

/** Every list that shows the Sites VODLoft knows, which picking them changes. */
const SITE_QUERIES = [
    'siteChoices', 'siteAuthentication', 'sitesSettings', 'sourceSites', 'localMediaProfileSites',
    'localMediaProfilesView', 'sources',
] as const

function SiteTile({site, picked, onToggle}: {site: SiteChoiceRead; picked: boolean; onToggle: () => void}) {
    return (
        <button
            type="button" className={`onboarding-site${picked ? ' is-picked' : ''}`} aria-pressed={picked}
            onClick={onToggle}
        >
            <span className="onboarding-site__icon"><SiteIcon site={site}/></span>
            <span className="onboarding-site__copy">
                <strong>{site.name}</strong>
                {site.pitch ? <small>{site.pitch}</small> : null}
            </span>
            <span className="onboarding-site__tick" aria-hidden="true">
                <FontAwesomeIcon icon={faIcon('fass', 'check')}/>
            </span>
        </button>
    )
}

/** Onboarding's Sites step: the user picks the Sites they use from the popular ones, or adds any other by its
 *  address. At least one is needed to continue. Continuing makes the picked Sites the ones VODLoft knows. */
export default function OnboardingSitesStep({onBack, onContinue}: Props) {
    const queryClient = useQueryClient()
    const {data: choices, error: loadError} = useSiteChoices()
    const [picked, setPicked] = useState<Set<string> | null>(null)
    const [saving, setSaving] = useState(false)
    const [error, setError] = useState<string | null>(null)

    // The Sites already added start picked, such as after going back to this step.
    useEffect(() => {
        if (choices && picked === null) setPicked(new Set(choices.filter((site) => site.added).map((site) => site.key)))
    }, [choices, picked])

    const chosen = picked ?? new Set<string>()
    const toggle = (key: string) => setPicked((current) => {
        const next = new Set(current ?? [])
        if (next.has(key)) next.delete(key)
        else next.add(key)
        return next
    })
    const pickedNames = (choices ?? []).filter((site) => chosen.has(site.key)).map((site) => site.name)

    const save = async () => {
        setSaving(true)
        setError(null)
        try {
            const response = await fetch(`${apiUrl()}/sources/site-choices`, {
                method: 'PUT',
                credentials: 'include',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({keys: [...chosen]}),
            })
            if (!response.ok) {
                const {error: message} = await getErrorMessageFromResponse(response)
                setError(message || 'VODLoft could not save the sites. Please try again.')
                return
            }
            await Promise.all(SITE_QUERIES.map((key) => queryClient.invalidateQueries({queryKey: [key]})))
            onContinue()
        } catch {
            setError('VODLoft could not save the sites. Check the connection and try again.')
        } finally {
            setSaving(false)
        }
    }

    return (
        <>
            <div className="onboarding-section-heading">
                <span className="onboarding-eyebrow">Sites</span>
                <h1>Which sites will you use?</h1>
                <p>
                    VODLoft downloads from YouTube and over a thousand other sites. Pick the ones you use. You can add
                    more at any time, and a site is also added when you paste a link from it.
                </p>
            </div>
            {loadError && <div className="form-error-card" role="alert">Could not load the sites: {loadError.message}</div>}
            {choices && (
                <div className="onboarding-sites" role="group" aria-label="Sites you use">
                    {choices.map((site) => (
                        <SiteTile key={site.key} site={site} picked={chosen.has(site.key)} onToggle={() => toggle(site.key)}/>
                    ))}
                </div>
            )}
            <div className="onboarding-sites-other">
                <AddSiteByLink
                    help="Another site? Type its address, such as nebula.tv, or paste a link to a page on it."
                    onAdded={(site) => setPicked((current) => new Set([...(current ?? []), site.key]))}
                />
            </div>
            {error && <div className="form-error-card" role="alert">{error}</div>}
            <div className="onboarding-stage-actions">
                <button className="btn" type="button" onClick={onBack}>Back</button>
                <span className={`onboarding-sites-count${chosen.size ? '' : ' is-needed'}`} role="status">
                    {chosen.size
                        ? `${chosen.size} ${chosen.size === 1 ? 'site' : 'sites'}: ${pickedNames.join(', ')}`
                        : <><FontAwesomeIcon icon={faIcon('fass', 'circle-info')}/> Pick at least one site to continue</>}
                </span>
                <button className="btn btn-primary" type="button" onClick={() => void save()} disabled={!chosen.size || saving}>
                    {saving ? 'Saving…' : 'Continue'}
                    <FontAwesomeIcon icon={faIcon('fass', 'arrow-right')}/>
                </button>
            </div>
        </>
    )
}
