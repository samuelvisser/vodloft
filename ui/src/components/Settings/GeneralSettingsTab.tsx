import type {SettingsValues} from '../../types/schemas/settings'
import {createSelectRegistry} from '../../utils/selectRegistry'
import type {SettingsTabProps} from './SettingsTabTypes'
import {
    DurationField,
    NumberField,
    SelectField,
    SettingsSection,
    TextField,
    ToggleField,
} from './SettingsControls'

const LogLevelReg = createSelectRegistry('LogLevel', {
    DEBUG: {label: 'DEBUG'},
    INFO: {label: 'INFO'},
    WARNING: {label: 'WARNING'},
    ERROR: {label: 'ERROR'},
    CRITICAL: {label: 'CRITICAL'},
})

export default function GeneralSettingsTab({draft, updateDraft, environmentVariableFor, errorFor}: SettingsTabProps) {
    return (
        <>
            <SettingsSection
                title="Application"
                description="Common settings that affect VODLoft throughout the interface and background services."
            >
                <TextField
                    id="settings-timezone"
                    label="Timezone"
                    value={draft.timezone}
                    error={errorFor('timezone')}
                    environmentVariable={environmentVariableFor('timezone')}
                    onChange={(value) => updateDraft((next) => { next.timezone = value })}
                    help={<>Use an <a href="https://en.wikipedia.org/wiki/List_of_tz_database_time_zones#List">IANA</a> timezone such as <code>Europe/Amsterdam</code>.</>}
                />
                <SelectField
                    id="settings-log-level"
                    label="Log level"
                    value={draft.logLevel}
                    registry={LogLevelReg}
                    error={errorFor('logLevel')}
                    environmentVariable={environmentVariableFor('logLevel')}
                    onChange={(value) => updateDraft((next) => {
                        next.logLevel = value as SettingsValues['logLevel']
                    })}
                    help="DEBUG is useful for troubleshooting but produces substantially more output."
                />
            </SettingsSection>

            <SettingsSection
                title="Log file"
                description="The Logs page starts empty each time VODLoft restarts. A log file keeps everything VODLoft logs, at the log level above, across restarts and updates."
            >
                <ToggleField
                    id="settings-log-file"
                    label="Write the log to a file"
                    checked={draft.logFile.enabled}
                    environmentVariable={environmentVariableFor('logFile.enabled')}
                    onChange={(checked) => updateDraft((next) => { next.logFile.enabled = checked })}
                    help={<>Writes <code>vodloft.log</code> in the <code>logs</code> folder next to <code>config.yml</code>.</>}
                />
                {draft.logFile.enabled && (
                    <>
                        <NumberField
                            id="settings-log-file-size"
                            label="Start a new file at"
                            value={draft.logFile.maxMegabytes}
                            min={1}
                            unit="MB"
                            error={errorFor('logFile.maxMegabytes')}
                            environmentVariable={environmentVariableFor('logFile.maxMegabytes')}
                            onChange={(value) => updateDraft((next) => { next.logFile.maxMegabytes = value })}
                            help="Once the file reaches this size, VODLoft renames it to vodloft.log.1 and starts a new one."
                        />
                        <NumberField
                            id="settings-log-file-kept"
                            label="Earlier files kept"
                            value={draft.logFile.keptFiles}
                            min={1}
                            unit="files"
                            error={errorFor('logFile.keptFiles')}
                            environmentVariable={environmentVariableFor('logFile.keptFiles')}
                            onChange={(value) => updateDraft((next) => { next.logFile.keptFiles = value })}
                            help="The oldest file is removed when there would be more. With DEBUG on, a busy day can fill several files."
                        />
                    </>
                )}
            </SettingsSection>

            <SettingsSection
                title="Login session"
                description="Controls how long a signed-in browser remains authenticated."
            >
                <DurationField
                    id="settings-session-ttl"
                    label="Session lifetime"
                    value={draft.loginSession.ttlSeconds}
                    backendUnit="seconds"
                    error={errorFor('loginSession.ttlSeconds')}
                    environmentVariable={environmentVariableFor('loginSession.ttlSeconds')}
                    onChange={(value) => updateDraft((next) => {
                        next.loginSession.ttlSeconds = value
                    })}
                />
            </SettingsSection>
        </>
    )
}
