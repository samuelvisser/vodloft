import type {QuickDownloadSettings} from '../../types/schemas/settings'
import {useSources} from '../../lib/queries'
import {createSelectRegistry} from '../../utils/selectRegistry'
import type {SettingsTabProps} from './SettingsTabTypes'
import {NumberField, SelectField, SettingsSection, ToggleField} from './SettingsControls'

const KindReg = createSelectRegistry('QuickDownloadKind', {
    video: {label: 'Video'},
    audio: {label: 'Audio'},
})

const QualityReg = createSelectRegistry('QuickDownloadQuality', {
    best: {label: 'Best'},
    '2160p': {label: '4K · 2160p'},
    '1440p': {label: '1440p'},
    '1080p': {label: '1080p'},
    '720p': {label: '720p'},
    '480p': {label: '480p'},
})

const QualityLimitReg = createSelectRegistry('QuickDownloadQualityLimit', {
    best: {label: 'No limit'},
    '2160p': {label: '4K · 2160p'},
    '1440p': {label: '1440p'},
    '1080p': {label: '1080p'},
    '720p': {label: '720p'},
    '480p': {label: '480p'},
})

const ContainerReg = createSelectRegistry('QuickDownloadContainer', {
    mp4: {label: 'MP4'},
    mkv: {label: 'MKV'},
})

const CodecReg = createSelectRegistry('QuickDownloadCodec', {
    auto: {label: 'Auto'},
    h264: {label: 'H.264'},
    h265: {label: 'H.265'},
    vp9: {label: 'VP9'},
    av1: {label: 'AV1'},
})

const FixedCodecReg = createSelectRegistry('QuickDownloadFixedCodec', {
    auto: {label: 'Any codec'},
    h264: {label: 'Always H.264'},
    h265: {label: 'Always H.265'},
    vp9: {label: 'Always VP9'},
    av1: {label: 'Always AV1'},
})

const AudioFormatReg = createSelectRegistry('QuickDownloadAudioFormat', {
    m4a: {label: 'M4A'},
    mp3: {label: 'MP3'},
})

const Mp3BitrateReg = createSelectRegistry('QuickDownloadMp3Bitrate', {
    '320': {label: '320 kbps'},
    '192': {label: '192 kbps'},
    '128': {label: '128 kbps'},
})

export default function QuickDownloadSettingsTab({draft, updateDraft, environmentVariableFor, errorFor}: SettingsTabProps) {
    const quick = draft.quickDownload
    const {data: sources} = useSources()
    const set = <K extends keyof QuickDownloadSettings>(key: K, value: QuickDownloadSettings[K]) => updateDraft((next) => {
        next.quickDownload[key] = value
    })
    const field = (key: keyof QuickDownloadSettings) => ({
        error: errorFor(`quickDownload.${key}`),
        environmentVariable: environmentVariableFor(`quickDownload.${key}`),
    })
    const allowedSources = quick.allowedSources.split(',').map((key) => key.trim()).filter(Boolean)
    const sourceAllowed = (key: string) => allowedSources.length === 0 || allowedSources.includes(key)
    const toggleSource = (key: string, allowed: boolean) => {
        const all = (sources ?? []).map((source) => source.id)
        const current = allowedSources.length ? allowedSources : all
        const next = allowed ? [...new Set([...current, key])] : current.filter((id) => id !== key)
        // Every Source allowed is the same as no rule, and stays so when a Source is added.
        set('allowedSources', all.every((id) => next.includes(id)) ? '' : next.join(','))
    }

    return (
        <>
            <SettingsSection
                title="Defaults"
                description="What the Quick download page suggests first. “Use these as my defaults next time” on the page changes them too."
            >
                <SelectField id="settings-quick-kind" label="Type" value={quick.defaultKind} registry={KindReg}
                             {...field('defaultKind')} onChange={(value) => set('defaultKind', value as QuickDownloadSettings['defaultKind'])}/>
                <SelectField id="settings-quick-quality" label="Video quality" value={quick.defaultQuality} registry={QualityReg}
                             {...field('defaultQuality')} onChange={(value) => set('defaultQuality', value as QuickDownloadSettings['defaultQuality'])}
                             help="The recommended option on the page. A video without this quality recommends the next one down."/>
                <SelectField id="settings-quick-container" label="Video format" value={quick.defaultContainer} registry={ContainerReg}
                             {...field('defaultContainer')} onChange={(value) => set('defaultContainer', value as QuickDownloadSettings['defaultContainer'])}/>
                <SelectField id="settings-quick-codec" label="Codec" value={quick.defaultCodec} registry={CodecReg}
                             {...field('defaultCodec')} onChange={(value) => set('defaultCodec', value as QuickDownloadSettings['defaultCodec'])}
                             help="Auto leaves the choice to the Source. Codecs are only offered for links that list them, such as yt-dlp links."/>
                <SelectField id="settings-quick-audio-format" label="Audio format" value={quick.defaultAudioFormat} registry={AudioFormatReg}
                             {...field('defaultAudioFormat')} onChange={(value) => set('defaultAudioFormat', value as QuickDownloadSettings['defaultAudioFormat'])}/>
                <SelectField id="settings-quick-mp3-bitrate" label="MP3 bitrate" value={String(quick.defaultMp3Bitrate)} registry={Mp3BitrateReg}
                             {...field('defaultMp3Bitrate')} onChange={(value) => set('defaultMp3Bitrate', Number(value))}/>
                <ToggleField id="settings-quick-embed-metadata" label="Embed title, show or channel and date" checked={quick.embedMetadata}
                             environmentVariable={environmentVariableFor('quickDownload.embedMetadata')}
                             onChange={(value) => set('embedMetadata', value)}/>
                <ToggleField id="settings-quick-embed-artwork" label="Embed cover art" checked={quick.embedArtwork}
                             environmentVariable={environmentVariableFor('quickDownload.embedArtwork')}
                             onChange={(value) => set('embedArtwork', value)}/>
            </SettingsSection>

            <SettingsSection
                title="Housekeeping"
                description="How long files wait in the temporary folder, and what VODLoft remembers about them."
            >
                <NumberField id="settings-quick-keep-downloaded" label="Keep a downloaded file for" unit="minutes"
                             value={quick.keepDownloadedMinutes} {...field('keepDownloadedMinutes')}
                             onChange={(value) => set('keepDownloadedMinutes', value)}
                             help="Time to retry a save that failed after the whole file was sent. 0 deletes the file at the last byte."/>
                <NumberField id="settings-quick-keep-unclaimed" label="Delete a file nobody downloads after" unit="hours" min={1}
                             value={quick.keepUnclaimedHours} {...field('keepUnclaimedHours')}
                             onChange={(value) => set('keepUnclaimedHours', value)}/>
                <NumberField id="settings-quick-keep-free" label="Space to keep free in the temporary folder" unit="GB" step={0.5}
                             value={quick.keepFreeGigabytes} {...field('keepFreeGigabytes')}
                             onChange={(value) => set('keepFreeGigabytes', value)}
                             help={`A quick download that would leave less free space in ${draft.downloadSettings.temporaryDownloadRoot} does not start.`}/>
                <ToggleField id="settings-quick-keep-history" label="Keep a history" checked={quick.keepHistory}
                             environmentVariable={environmentVariableFor('quickDownload.keepHistory')}
                             onChange={(value) => set('keepHistory', value)}
                             help="What was downloaded, from where, as what and how it ended. No files or paths are kept."/>
                <NumberField id="settings-quick-history-days" label="Forget history after" unit="days" min={1}
                             value={quick.historyRetentionDays} {...field('historyRetentionDays')}
                             onChange={(value) => set('historyRetentionDays', value)}/>
            </SettingsSection>

            <SettingsSection
                title="Rules"
                description="Optional limits on what the Quick download page lets anyone choose. All off by default. VODLoft checks them itself, so a choice the rules don't allow never starts."
            >
                <SelectField id="settings-quick-max-quality" label="Highest quality" value={quick.maxQuality} registry={QualityLimitReg}
                             {...field('maxQuality')} onChange={(value) => set('maxQuality', value as QuickDownloadSettings['maxQuality'])}
                             help="Higher choices are greyed out, and Best is held to this height."/>
                <SelectField id="settings-quick-fixed-codec" label="Codec" value={quick.fixedCodec} registry={FixedCodecReg}
                             {...field('fixedCodec')} onChange={(value) => set('fixedCodec', value as QuickDownloadSettings['fixedCodec'])}
                             help="Only streams in this codec, for links that list their codecs, such as yt-dlp links. A link without one does not start."/>
                <NumberField id="settings-quick-max-file" label="Largest file" unit="GB" step={0.5}
                             value={quick.maxFileGigabytes} {...field('maxFileGigabytes')}
                             onChange={(value) => set('maxFileGigabytes', value)}
                             help="Checked before starting when the Source reports a size, and again while fetching from yt-dlp. 0 is no limit."/>
                <NumberField id="settings-quick-max-duration" label="Longest video" unit="minutes"
                             value={quick.maxDurationMinutes} {...field('maxDurationMinutes')}
                             onChange={(value) => set('maxDurationMinutes', value)}
                             help="Checked when the Source reports how long a video is. 0 is no limit."/>
                <ToggleField id="settings-quick-allow-mp4" label="Allow MP4 video" checked={quick.allowMp4}
                             onChange={(value) => set('allowMp4', value)}/>
                <ToggleField id="settings-quick-allow-mkv" label="Allow MKV video" checked={quick.allowMkv}
                             onChange={(value) => set('allowMkv', value)}/>
                <ToggleField id="settings-quick-allow-m4a" label="Allow M4A audio" checked={quick.allowM4a}
                             onChange={(value) => set('allowM4a', value)}/>
                <ToggleField id="settings-quick-allow-mp3" label="Allow MP3 audio" checked={quick.allowMp3}
                             onChange={(value) => set('allowMp3', value)}/>
                {(sources ?? []).map((source) => (
                    <ToggleField key={source.id} id={`settings-quick-source-${source.id}`}
                                 label={`Allow ${source.name}`} checked={sourceAllowed(source.id)}
                                 environmentVariable={environmentVariableFor('quickDownload.allowedSources')}
                                 onChange={(value) => toggleSource(source.id, value)}/>
                ))}
                <ToggleField id="settings-quick-lock" label="Lock choices to the defaults" checked={quick.lockToDefaults}
                             environmentVariable={environmentVariableFor('quickDownload.lockToDefaults')}
                             onChange={(value) => set('lockToDefaults', value)}
                             help="The page shows only the link box and the defaults."/>
            </SettingsSection>
        </>
    )
}
