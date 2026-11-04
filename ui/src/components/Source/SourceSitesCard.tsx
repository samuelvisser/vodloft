import {useMemo, useState} from 'react'
import {useQueryClient} from '@tanstack/react-query'

import {saveSourceSite, useSourceSites, useSourceLookup} from '../../lib/queries'
import type {SourceSiteRead} from '../../types/schemas/source'
import {createSelectRegistry} from '../../utils/selectRegistry'
import SimpleSelect from '../common/SimpleSelect'
import SourceSection from './SourceSection'

function SiteSourceSelect({row, disabled, onChange}: {
    row: SourceSiteRead
    disabled: boolean
    onChange: (sourceKey: string) => void
}) {
    const sources = useSourceLookup()
    const registry = useMemo(() => createSelectRegistry(
        `SourceSite:${row.key}`,
        Object.fromEntries(row.sourceKeys.map((key) => [
            key,
            {label: `${sources.name(key)}${key === row.defaultSourceKey ? ' (default)' : ''}`},
        ])),
        row.sourceKeys,
    ), [row.key, row.sourceKeys, row.defaultSourceKey, sources])

    return (
        <SimpleSelect
            aria-label={`Source to ask first for ${row.name}`}
            registry={registry}
            value={row.preferredSourceKey ?? row.defaultSourceKey}
            isDisabled={disabled}
            menuPlacement="auto"
            onChange={onChange}
        />
    )
}

/** Which Source VODLoft asks first for links on a site that several Sources can handle. */
export default function SourceSitesCard() {
    const queryClient = useQueryClient()
    const {data: sites, error: loadError} = useSourceSites()
    const [saving, setSaving] = useState<string | null>(null)
    const [error, setError] = useState<string | null>(null)

    const choose = async (row: SourceSiteRead, sourceKey: string) => {
        setSaving(row.key)
        setError(null)
        try {
            const saved = await saveSourceSite(row.key, sourceKey === row.defaultSourceKey ? null : sourceKey)
            queryClient.setQueryData<SourceSiteRead[]>(['sourceSites'], (current) =>
                current?.map((item) => (item.key === saved.key ? saved : item)))
        } catch (exc) {
            setError(exc instanceof Error ? exc.message : String(exc))
        } finally {
            setSaving(null)
        }
    }

    const rows = (sites ?? []).filter((row) => row.sourceKeys.length > 1)
    if (!loadError && !rows.length) return null
    return (
        <SourceSection
            title="Sites"
            description="Some sites can be handled by more than one Source. VODLoft asks the chosen Source first, and you can still pick another one on the Add media page."
        >
            {loadError && <p className="source-setting-error" role="alert">Could not load sites: {loadError.message}</p>}
            {error && <p className="source-setting-error" role="alert">{error}</p>}
            {rows.length > 0 && (
                <table className="source-site-table">
                    <thead>
                        <tr><th scope="col">Site</th><th scope="col">Ask first</th></tr>
                    </thead>
                    <tbody>
                        {rows.map((row) => (
                            <tr key={row.key}>
                                <td>{row.name}<span className="source-site-domains"> · {row.domains.join(', ')}</span></td>
                                <td>
                                    <SiteSourceSelect
                                        row={row}
                                        disabled={saving === row.key}
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
