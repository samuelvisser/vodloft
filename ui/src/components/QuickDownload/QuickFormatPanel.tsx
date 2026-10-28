import {useEffect, useId} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import {CODEC_NAMES, CODEC_NOTES, qualityLabel, sizeLabel, videoOption} from '../../lib/quickDownloads'
import {
    MP3_BITRATES,
    QUICK_CODECS,
    type QuickChoice,
    type QuickCodec,
    type QuickDownloadOptions,
} from '../../types/schemas/quick_download'

type QuickFormatPanelProps = {
    open: boolean
    options: QuickDownloadOptions
    sourceName: string
    choice: QuickChoice
    initial: QuickChoice
    saveAsDefaults: boolean
    onChange: (choice: QuickChoice) => void
    onSaveAsDefaultsChange: (value: boolean) => void
    onClose: () => void
}

function Choice({selected, disabled, onPick, label, note, size}: {
    selected: boolean; disabled?: boolean; onPick: () => void; label: string; note?: string; size?: number | null
}) {
    return (
        <button
            type="button"
            role="radio"
            aria-checked={selected}
            className={`quick-panel-choice${selected ? ' is-selected' : ''}`}
            disabled={disabled}
            onClick={onPick}
        >
            <span className="quick-option-radio" aria-hidden="true"/>
            <span>{label}{note && <small> {note}</small>}</span>
            <span className="quick-muted">{disabled ? '–' : sizeLabel(size)}</span>
        </button>
    )
}

/**
 * Format and codec for the selected option: a side panel on a desktop, a
 * sheet from the bottom on a phone. Choices the link does not offer are
 * greyed out with the reason.
 */
export default function QuickFormatPanel({
    open, options, sourceName, choice, initial, saveAsDefaults, onChange, onSaveAsDefaultsChange, onClose,
}: QuickFormatPanelProps) {
    const titleId = useId()

    useEffect(() => {
        if (!open) return
        const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
        window.addEventListener('keydown', onKey)
        return () => window.removeEventListener('keydown', onKey)
    }, [open, onClose])

    if (!open) return null
    const video = choice.kind === 'video' ? videoOption(options, choice.quality) : undefined
    const offered = new Set(video?.codecs.map((c) => c.codec) ?? [])
    const set = (change: Partial<QuickChoice>) => onChange({...choice, ...change})

    return (
        <div className="quick-panel-overlay" role="presentation" onClick={onClose}>
            <aside
                className="quick-panel"
                role="dialog"
                aria-modal="true"
                aria-labelledby={titleId}
                onClick={(event) => event.stopPropagation()}
            >
                <header className="quick-panel-header">
                    <h2 id={titleId}>Format and codec</h2>
                    <button type="button" className="icon-btn" onClick={onClose} aria-label="Close">
                        <FontAwesomeIcon icon={faIcon('fass', 'xmark')}/>
                    </button>
                </header>
                <p className="quick-muted">
                    For: {choice.kind === 'audio' ? 'audio' : `${qualityLabel(choice.quality)} video`}. Changes apply to this download.
                </p>

                {!options.formatChoices && (
                    <p className="quick-panel-note">
                        {sourceName} downloads as Best MP4 video or M4A audio. Other formats are not offered for it yet.
                    </p>
                )}

                {choice.kind === 'video' && options.formatChoices && (
                    <>
                        <fieldset className="quick-panel-field">
                            <legend>Format</legend>
                            <span className="quick-chips">
                                {(['mp4', 'mkv'] as const).map((container) => (
                                    <button key={container} type="button" aria-pressed={choice.container === container}
                                            className={`quick-chip${choice.container === container ? ' is-on' : ''}`}
                                            onClick={() => set({container})}>
                                        {container.toUpperCase()}
                                    </button>
                                ))}
                            </span>
                            <small className="quick-muted">MP4 plays almost everywhere. MKV keeps VP9 and AV1 with Opus audio without converting.</small>
                        </fieldset>
                        <fieldset className="quick-panel-field" role="radiogroup">
                            <legend>Video codec</legend>
                            <Choice
                                selected={choice.codec == null}
                                onPick={() => set({codec: null})}
                                label={`Auto${video?.codec ? ` · ${CODEC_NAMES[video.codec as QuickCodec] ?? video.codec}` : ''}`}
                                note={`${sourceName} picks`}
                                size={video?.sizeBytes}
                            />
                            {QUICK_CODECS.map((codec) => (
                                <Choice
                                    key={codec}
                                    selected={choice.codec === codec}
                                    disabled={!offered.has(codec)}
                                    onPick={() => set({codec})}
                                    label={CODEC_NAMES[codec]}
                                    note={offered.has(codec) ? CODEC_NOTES[codec] : 'not offered for this video'}
                                    size={video?.codecs.find((c) => c.codec === codec)?.sizeBytes}
                                />
                            ))}
                        </fieldset>
                    </>
                )}

                {choice.kind === 'audio' && options.formatChoices && (
                    <>
                        <fieldset className="quick-panel-field">
                            <legend>Format</legend>
                            <span className="quick-chips">
                                {(['m4a', 'mp3'] as const).map((audioFormat) => (
                                    <button key={audioFormat} type="button" aria-pressed={choice.audioFormat === audioFormat}
                                            className={`quick-chip${choice.audioFormat === audioFormat ? ' is-on' : ''}`}
                                            onClick={() => set({audioFormat})}>
                                        {audioFormat.toUpperCase()}
                                    </button>
                                ))}
                            </span>
                            <small className="quick-muted">M4A keeps the original audio. MP3 converts it, for older players and car stereos.</small>
                        </fieldset>
                        {choice.audioFormat === 'mp3' && (
                            <fieldset className="quick-panel-field" role="radiogroup">
                                <legend>MP3 quality</legend>
                                {MP3_BITRATES.map((bitrate) => (
                                    <Choice
                                        key={bitrate}
                                        selected={(choice.audioBitrate ?? 320) === bitrate}
                                        onPick={() => set({audioBitrate: bitrate})}
                                        label={`${bitrate} kbps`}
                                        size={options.audio.find((a) => a.audioFormat === 'mp3' && a.bitrate === bitrate)?.sizeBytes}
                                    />
                                ))}
                            </fieldset>
                        )}
                    </>
                )}

                <fieldset className="quick-panel-field">
                    <legend>Inside the file</legend>
                    <label className="quick-check">
                        <input type="checkbox" checked={choice.embedMetadata}
                               onChange={(event) => set({embedMetadata: event.target.checked})}/>
                        Title, show or channel and date
                    </label>
                    <label className="quick-check">
                        <input type="checkbox" checked={choice.embedArtwork}
                               onChange={(event) => set({embedArtwork: event.target.checked})}/>
                        Cover art
                    </label>
                </fieldset>

                <label className="quick-check quick-panel-defaults">
                    <input type="checkbox" checked={saveAsDefaults}
                           onChange={(event) => onSaveAsDefaultsChange(event.target.checked)}/>
                    Use these as my defaults next time
                </label>

                <div className="quick-panel-actions">
                    <button type="button" className="btn" onClick={() => onChange(initial)}>Reset</button>
                    <button type="button" className="btn btn-primary" onClick={onClose}>Done</button>
                </div>
            </aside>
        </div>
    )
}
