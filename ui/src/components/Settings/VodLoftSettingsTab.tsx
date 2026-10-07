import type {SettingsTabProps} from './SettingsTabTypes'
import {DurationField, NumberField, SelectField, SettingsSection, TextField, ToggleField} from './SettingsControls'

export default function VodLoftSettingsTab({
    tab,
    draft,
    updateDraft,
    environmentVariableFor,
    errorFor,
    isFieldDirty,
    downloadStorage,
}: SettingsTabProps & {tab: 'downloads' | 'automation' | 'advanced'}) {
    if (tab === 'downloads') {
        const storageInspectionIsCurrent = ![
            'downloadSettings.downloadRoot',
            'downloadSettings.temporaryDownloadRoot',
            'downloadSettings.downloadMode',
        ].some((path) => isFieldDirty(path as Parameters<typeof isFieldDirty>[0]))
        const downloadRootIsRemote = downloadStorage?.downloadRoot.storageKind === 'remote'
        const temporaryRootIsRemote = downloadStorage?.temporaryDownloadRoot.storageKind === 'remote'
        const temporarySharesRemoteFilesystem = (
            draft.downloadSettings.downloadMode === 'temporary'
            && downloadRootIsRemote
            && temporaryRootIsRemote
            && downloadStorage?.sameFilesystem === true
        )

        let storageAdvisory: string | null = null
        if (storageInspectionIsCurrent) {
            if (temporarySharesRemoteFilesystem) {
                storageAdvisory = 'The temporary folder and media library are on the same network filesystem. Temporary mode therefore does not keep remuxing and metadata processing local. Use a local temporary folder to reduce repeated network I/O.'
            } else if (draft.downloadSettings.downloadMode === 'temporary' && temporaryRootIsRemote) {
                storageAdvisory = 'The temporary download folder appears to be on network storage. Remuxing and metadata embedding repeatedly read and rewrite media there, so local temporary storage can substantially improve processing performance.'
            } else if (draft.downloadSettings.downloadMode === 'direct' && downloadRootIsRemote) {
                storageAdvisory = 'The media library appears to be on a network filesystem. Direct mode performs remuxing and metadata embedding against that storage; temporary mode with a local temporary folder can substantially reduce network I/O.'
            }
        }

        return <SettingsSection title="Media storage and downloads" description="Acquisitions use recoverable publication. Representation and presentation choices belong to Local Media Profiles.">
        <TextField id="settings-download-root" label="Library folder" value={draft.downloadSettings.downloadRoot}
            error={errorFor('downloadSettings.downloadRoot')} environmentVariable={environmentVariableFor('downloadSettings.downloadRoot')}
            onChange={value => updateDraft(next => {next.downloadSettings.downloadRoot = value})}
            help="The /downloads prefix in output templates maps to this folder. Keep this storage mounted and back it up together with configuration." wide/>
        <SelectField id="settings-download-mode" label="Default download behavior" value={draft.downloadSettings.downloadMode}
            options={['temporary', 'direct']}
            optionLabels={{temporary: 'Save to temporary folder first', direct: 'Save directly to library'}}
            error={errorFor('downloadSettings.downloadMode')}
            environmentVariable={environmentVariableFor('downloadSettings.downloadMode')}
            onChange={value => updateDraft(next => {next.downloadSettings.downloadMode = value as typeof next.downloadSettings.downloadMode})}
            help="Temporary mode is the default. It keeps acquisition and processing work out of the final library until publication, which is especially useful for network-backed libraries."/>
        <TextField id="settings-temporary-download-root" label="Temporary download folder" value={draft.downloadSettings.temporaryDownloadRoot}
            error={errorFor('downloadSettings.temporaryDownloadRoot')}
            environmentVariable={environmentVariableFor('downloadSettings.temporaryDownloadRoot')}
            onChange={value => updateDraft(next => {next.downloadSettings.temporaryDownloadRoot = value})}
            help="Defaults to local operating-system temporary storage. Keeping this local avoids repeated remuxing and metadata I/O against SMB, NFS, or other network storage." wide/>
        {storageAdvisory ? <div className="settings-storage-advisory settings-field--wide" role="status">
            <strong>Storage performance</strong>
            <span>{storageAdvisory}</span>
        </div> : null}
        <NumberField id="settings-concurrent-downloads" label="Concurrent acquisitions" value={draft.downloadSettings.maxConcurrentDownloads} min={1}
            error={errorFor('downloadSettings.maxConcurrentDownloads')} environmentVariable={environmentVariableFor('downloadSettings.maxConcurrentDownloads')}
            onChange={value => updateDraft(next => {next.downloadSettings.maxConcurrentDownloads = value})} help="Applies after restart. Source, Domain and account limits also apply."/>
        <NumberField id="settings-download-attempts" label="Maximum acquisition attempts" value={draft.downloadSettings.maxDownloadAttempts} min={1}
            error={errorFor('downloadSettings.maxDownloadAttempts')} environmentVariable={environmentVariableFor('downloadSettings.maxDownloadAttempts')}
            onChange={value => updateDraft(next => {next.downloadSettings.maxDownloadAttempts = value})}/>
        <DurationField id="settings-download-timeout" label="Acquisition time limit" value={draft.downloadSettings.downloadTimeoutSeconds} backendUnit="seconds"
            error={errorFor('downloadSettings.downloadTimeoutSeconds')} environmentVariable={environmentVariableFor('downloadSettings.downloadTimeoutSeconds')}
            onChange={value => updateDraft(next => {next.downloadSettings.downloadTimeoutSeconds = value})} help="Maximum duration of one Source acquisition, including processing."/>
        <SelectField id="settings-filename-mode" label="Filename compatibility" value={draft.downloadSettings.filenameRestrictionMode}
            options={['unrestricted', 'windows', 'restricted']} error={errorFor('downloadSettings.filenameRestrictionMode')}
            environmentVariable={environmentVariableFor('downloadSettings.filenameRestrictionMode')}
            onChange={value => updateDraft(next => {next.downloadSettings.filenameRestrictionMode = value as typeof next.downloadSettings.filenameRestrictionMode})}
            help="Affects generated paths. Display titles retain the original characters."/>
    </SettingsSection>
    }
    if (tab === 'automation') return <SettingsSection title="Background work" description="Collection refresh intervals, member selection and retention are configured in Collection Download Profiles. Source updates have their own policies in Management.">
        <ToggleField id="settings-scheduler-enabled" label="Enable automatic acquisition and Source updates" checked={draft.scheduler.enabled}
            environmentVariable={environmentVariableFor('scheduler.enabled')}
            onChange={checked => updateDraft(next => {next.scheduler.enabled = checked})}
            help="Manual operations, interrupted-job recovery, publication repair, playback cleanup and media-server retries continue." wide/>
        <DurationField id="settings-retry-backoff" label="Acquisition retry backoff" value={draft.scheduler.retryBackoffSeconds} backendUnit="seconds"
            error={errorFor('scheduler.retryBackoffSeconds')} environmentVariable={environmentVariableFor('scheduler.retryBackoffSeconds')}
            onChange={value => updateDraft(next => {next.scheduler.retryBackoffSeconds = value})}
            help="Each retry doubles this delay. Rate-limited work waits at least five minutes."/>
    </SettingsSection>
    return <><SettingsSection title="Encryption key files" description="Retain the encryption key with configuration so Source accounts, media-server tokens and browser sessions remain readable.">
        <TextField id="settings-secret-key-file" label="Secret key file override" value={draft.crypto.secretKeyFile ?? ''}
            error={errorFor('crypto.secretKeyFile')} environmentVariable={environmentVariableFor('crypto.secretKeyFile')}
            onChange={value => updateDraft(next => {next.crypto.secretKeyFile = value || null})} help="Leave empty to use the generated key. Applies after restart." wide/>
        <TextField id="settings-default-secret-file" label="Generated key file" value={draft.crypto.defaultSecretFile}
            error={errorFor('crypto.defaultSecretFile')} environmentVariable={environmentVariableFor('crypto.defaultSecretFile')}
            onChange={value => updateDraft(next => {next.crypto.defaultSecretFile = value})} help="Changing this path requires the same key material at the new location." wide/>
    </SettingsSection><SettingsSection title="Configuration precedence" description="Environment variables take precedence over config.yml, followed by built-in defaults.">
        <p>Configure website accounts, trusted Source releases and delivery connections in Management.</p>
    </SettingsSection></>
}
