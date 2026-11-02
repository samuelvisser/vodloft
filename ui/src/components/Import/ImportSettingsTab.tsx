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
                    defaultOpen={importers.data.length === 1 || Boolean(importer.upload.upload)}
                >
                    <ImportFlow importer={importer}/>
                </SettingsSection>
            ))}
        </>
    )
}
