import {useSettings} from '../../lib/settings'
import {useSpeedLimitStatus} from '../../lib/speedLimit'
import type {SpeedLimitStatus} from '../../types/schemas/settings'
import ReadMore from '../../utils/ReadMore'
import {createSelectRegistry} from '../../utils/selectRegistry'
import type {SettingsTabProps} from './SettingsTabTypes'
import {NumberField, SelectField, SettingsSection, TextField, ToggleField} from './SettingsControls'

const SpeedLimitModeReg = createSelectRegistry('SpeedLimitMode', {
    full: {label: 'Full speed'},
    streaming: {label: 'Leave room for streaming'},
    custom: {label: 'Custom limit'},
})

function speed(mbps: number): string {
    return `${mbps.toLocaleString(undefined, {maximumFractionDigits: 1})} MB/s`
}

function statusLine(status: SpeedLimitStatus, mode: string): string {
    if (status.pausedUntil) {
        const time = status.pausedUntil.toLocaleTimeString(undefined, {hour: '2-digit', minute: '2-digit'})
        return `Downloads are paused until ${time}.`
    }
    if (mode === 'streaming') {
        if (status.estimateMbps === null || status.limitMbps === null) {
            return 'VODLoft has not measured your connection yet, so downloads run at full speed until a few have finished.'
        }
        return `Your connection reaches about ${speed(status.estimateMbps)}, so downloads use up to ${speed(status.limitMbps)} together.`
    }
    if (status.limitMbps !== null) return `Downloads use up to ${speed(status.limitMbps)} together.`
    return status.estimateMbps === null
        ? 'Downloads use all the speed they can get.'
        : `Downloads use all the speed they can get. Your connection reaches about ${speed(status.estimateMbps)}.`
}

/** Settings › Downloads › Speed: how much of the connection downloads may use, and a pause at night. */
export default function SpeedSettings({draft, updateDraft, errorFor, environmentVariableFor}: SettingsTabProps) {
    const saved = useSettings().data?.values.downloadSettings
    const savedVersion = saved
        ? [saved.speedLimitMode, saved.speedLimitMbps, saved.pauseAtNight, saved.pauseStart, saved.pauseEnd].join('|')
        : null
    const status = useSpeedLimitStatus(savedVersion).data
    const settings = draft.downloadSettings

    return (
        <SettingsSection
            title="Speed"
            description="How much of your internet connection downloads may use, so watching something at the same time keeps working."
        >
            <SelectField
                id="settings-speed-limit-mode"
                label="Download speed"
                value={settings.speedLimitMode}
                registry={SpeedLimitModeReg}
                error={errorFor('downloadSettings.speedLimitMode')}
                environmentVariable={environmentVariableFor('downloadSettings.speedLimitMode')}
                onChange={(value) => updateDraft((next) => {
                    next.downloadSettings.speedLimitMode = value as typeof settings.speedLimitMode
                })}
                help={
                    <ReadMore summary="The limit is shared by every download that runs at the same time.">
                        <p>
                            Leave room for streaming keeps downloads to about half of your connection. VODLoft learns how
                            fast your connection is from downloads that ran at full speed, so it needs a few downloads
                            before it starts limiting.
                        </p>
                    </ReadMore>
                }
            />
            {settings.speedLimitMode === 'custom' ? (
                <NumberField
                    id="settings-speed-limit-mbps"
                    label="Limit"
                    value={settings.speedLimitMbps}
                    min={0.1}
                    step={0.5}
                    unit="MB/s"
                    error={errorFor('downloadSettings.speedLimitMbps')}
                    environmentVariable={environmentVariableFor('downloadSettings.speedLimitMbps')}
                    onChange={(value) => updateDraft((next) => {
                        next.downloadSettings.speedLimitMbps = value
                    })}
                    help="Megabytes per second for all downloads together. 1 MB/s is 8 Mbit/s."
                />
            ) : null}
            {status && (!saved || saved.speedLimitMode === settings.speedLimitMode) ? (
                <div className="settings-storage-advisory settings-field--wide" role="status">
                    <strong>Right now</strong>
                    <span>{statusLine(status, settings.speedLimitMode)}</span>
                </div>
            ) : null}
            <ToggleField
                id="settings-pause-at-night"
                label="Pause downloads at night"
                checked={settings.pauseAtNight}
                environmentVariable={environmentVariableFor('downloadSettings.pauseAtNight')}
                onChange={(checked) => updateDraft((next) => {
                    next.downloadSettings.pauseAtNight = checked
                })}
                help="Downloads wait between these times and continue when the pause ends. Checking for new episodes keeps going."
                wide
            />
            {settings.pauseAtNight ? (
                <>
                    <TextField
                        id="settings-pause-start"
                        label="Pause from"
                        inputType="time"
                        value={settings.pauseStart}
                        error={errorFor('downloadSettings.pauseStart')}
                        environmentVariable={environmentVariableFor('downloadSettings.pauseStart')}
                        onChange={(value) => updateDraft((next) => {
                            next.downloadSettings.pauseStart = value
                        })}
                    />
                    <TextField
                        id="settings-pause-end"
                        label="Until"
                        inputType="time"
                        value={settings.pauseEnd}
                        error={errorFor('downloadSettings.pauseEnd')}
                        environmentVariable={environmentVariableFor('downloadSettings.pauseEnd')}
                        onChange={(value) => updateDraft((next) => {
                            next.downloadSettings.pauseEnd = value
                        })}
                    />
                </>
            ) : null}
        </SettingsSection>
    )
}
