import {useMemo, useState} from 'react'
import {useQueryClient} from '@tanstack/react-query'

import {saveSourceDomain, useSourceDomains, useSourceLookup} from '../../lib/queries'
import type {SourceDomainRead} from '../../types/schemas/source'
import {createSelectRegistry} from '../../utils/selectRegistry'
import SimpleSelect from '../common/SimpleSelect'
import SourceSection from './SourceSection'

function DomainSourceSelect({row, disabled, onChange}: {
    row: SourceDomainRead
    disabled: boolean
    onChange: (sourceKey: string) => void
}) {
    const sources = useSourceLookup()
    const registry = useMemo(() => createSelectRegistry(
        `SourceDomain:${row.domain}`,
        Object.fromEntries(row.sourceKeys.map((key) => [
            key,
            {label: `${sources.name(key)}${key === row.defaultSourceKey ? ' (default)' : ''}`},
        ])),
        row.sourceKeys,
    ), [row.domain, row.sourceKeys, row.defaultSourceKey, sources])

    return (
        <SimpleSelect
            aria-label={`Source to ask first for ${row.domain}`}
            registry={registry}
            value={row.preferredSourceKey ?? row.defaultSourceKey}
            isDisabled={disabled}
            menuPlacement="auto"
            onChange={onChange}
        />
    )
}

/** Which Source VODLoft asks first for links on a site that several Sources can handle. */
export default function SourceDomainsCard() {
    const queryClient = useQueryClient()
    const {data: domains, error: loadError} = useSourceDomains()
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
        <SourceSection
            title="Sites"
            description="Some sites can be handled by more than one Source. VODLoft asks the chosen Source first, and you can still pick another one on the Add media page."
        >
            {loadError && <p className="source-setting-error" role="alert">Could not load sites: {loadError.message}</p>}
            {error && <p className="source-setting-error" role="alert">{error}</p>}
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
                                    <DomainSourceSelect
                                        row={row}
                                        disabled={saving === row.domain}
                                        onChange={(sourceKey) => void choose(row, sourceKey)}
                                    />
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            )}
        </SourceSection>
    )
}
