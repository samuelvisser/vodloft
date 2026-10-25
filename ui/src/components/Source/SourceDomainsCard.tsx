import {useState} from 'react'
import {useQueryClient} from '@tanstack/react-query'

import {saveSourceDomain, useSourceDomains, useSourceLookup} from '../../lib/queries'
import type {SourceDomainRead} from '../../types/schemas/source'

/** Which Source VODLoft asks first for links on a site that several Sources can handle. */
export default function SourceDomainsCard() {
    const queryClient = useQueryClient()
    const {data: domains, error: loadError} = useSourceDomains()
    const sources = useSourceLookup()
    const [saving, setSaving] = useState<string | null>(null)
    const [error, setError] = useState<string | null>(null)

    const choose = async (row: SourceDomainRead, sourceKey: string) => {
        setSaving(row.domain)
        setError(null)
        try {
            const saved = await saveSourceDomain(row.domain, sourceKey === row.defaultSourceKey ? null : sourceKey)
            queryClient.setQueryData<SourceDomainRead[]>(['sourceDomains'], (current) =>
                current?.map((item) => (item.domain === saved.domain ? saved : item)))
        } catch (exc) {
            setError(exc instanceof Error ? exc.message : String(exc))
        } finally {
            setSaving(null)
        }
    }

    const rows = (domains ?? []).filter((row) => row.sourceKeys.length > 1)
    if (!loadError && !rows.length) return null
    return (
        <section className="card source-card" aria-labelledby="source-domains-title">
            <div className="card-body">
                <div className="source-card-header">
                    <h3 id="source-domains-title">Sites</h3>
                </div>
                <p className="view-description">
                    Some sites can be handled by more than one Source. VODLoft asks the chosen Source first, and you
                    can still pick another one on the Add media page.
                </p>
                {loadError && <p className="source-setting-error" role="alert">Could not load sites: {loadError.message}</p>}
                {error && <p className="source-setting-error" role="alert">{error}</p>}
            </div>
            {rows.length > 0 && (
                <table className="source-domain-table">
                    <thead>
                        <tr><th scope="col">Site</th><th scope="col">Ask first</th></tr>
                    </thead>
                    <tbody>
                        {rows.map((row) => (
                            <tr key={row.domain}>
                                <td>{row.domain}</td>
                                <td>
                                    <select
                                        aria-label={`Source to ask first for ${row.domain}`}
                                        value={row.preferredSourceKey ?? row.defaultSourceKey}
                                        disabled={saving === row.domain}
                                        onChange={(event) => void choose(row, event.target.value)}
                                    >
                                        {row.sourceKeys.map((key) => (
                                            <option key={key} value={key}>
                                                {sources.name(key)}{key === row.defaultSourceKey ? ' (default)' : ''}
                                            </option>
                                        ))}
                                    </select>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            )}
        </section>
    )
}
