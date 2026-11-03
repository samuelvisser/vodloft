import {useState} from 'react'
import {useSearchParams} from 'react-router-dom'
import './Import.css'
import {SettingsLoading, SettingsSection} from '../Settings/SettingsControls'
import ImportFlow from './ImportFlow'
import {useImporters} from '../../lib/imports'

const DESCRIPTIONS: Record<string, string> = {
    pinchflat: 'Sources, media profiles, downloaded files and settings from Pinchflat.',
    wireloft: 'Everything from WireLoft: shows, movies, feeds, Download Profiles, files and the Daily Wire sign-in.',
}

/** Settings › Import: bring over another program's library. */
export default function ImportSettingsTab() {
    const importers = useImporters()
    // ?open=pinchflat opens that importer's card, such as after an import started during onboarding.
    const [params] = useSearchParams()
    const openKey = params.get('open')
    // An importer reads its upload once its card is first opened, and keeps going when the card closes again.
    const [opened, setOpened] = useState<ReadonlySet<string>>(() => new Set(openKey ? [openKey] : []))

    if (importers.isError) return <p role="alert">Could not load the importers: {importers.error.message}</p>
    if (!importers.data) return <SettingsLoading/>

    return (
        <>
            {importers.data.map((importer) => (
                <SettingsSection
                    key={importer.key}
                    title={importer.name}
                    description={DESCRIPTIONS[importer.key] ?? `Bring over ${importer.name}.`}
                    bodyClassName="import-section"
                    defaultOpen={importer.key === openKey}
                    onToggle={(open) => {
                        if (open) setOpened((current) => current.has(importer.key) ? current : new Set([...current, importer.key]))
                    }}
                >
                    {opened.has(importer.key) && <ImportFlow importer={importer}/>}
                </SettingsSection>
            ))}
        </>
    )
}
