import {useState} from 'react'
import {useWatch, type UseFormReturn} from 'react-hook-form'
import Select from 'react-select'
import Switch from 'react-switch'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'

import {faIcon} from '../../icons/faIcon'
import {PreferredFormatReg} from '../../types/local_media_profile'
import {
    AudioCodecReg,
    AudioFormatReg,
    AudioLanguageReg,
    CODEC_TAGS,
    CodecFallbackReg,
    ContainerReg,
    GOAL_PRESETS,
    LADDER_STEPS,
    QualityGoalReg,
    VideoCodecReg,
    codecSummary,
    type CodecChoice,
    type QualityGoal,
} from '../../types/quality'
import SegmentedOptions from '../SegmentedOptions/SegmentedOptions'
import './QualityField.css'

type Props = {
    form: UseFormReturn<any>
    /** Audio only is offered for Collections and single videos, not for movies. */
    allowAudioOnly?: boolean
    /** The Daily Wire's HLS bundle, for Collection profiles only. */
    allowHls?: boolean
}

const OPTIONS = {shouldDirty: true, shouldValidate: true} as const

/** Quality design D: an "up to" resolution ladder, a goal, and your own codec order. */
export default function QualityField({form, allowAudioOnly = true, allowHls = false}: Props) {
    const {control, setValue, formState: {errors}} = form
    const [preferredFormat, goal, videoCodecs, codecFallback, container, audioCodec, audioFormat, audioLanguage] = useWatch({
        control,
        name: ['preferredFormat', 'qualityGoal', 'videoCodecs', 'codecFallback', 'container', 'audioCodec', 'audioFormat', 'audioLanguage'],
    }) as [string, QualityGoal, CodecChoice[], string, string, string, string, string | null]
    const [dragging, setDragging] = useState<number | null>(null)
    const audioOnly = preferredFormat === 'format_audio_only'
    const hls = preferredFormat === 'format_hls'
    const chosenIndex = LADDER_STEPS.indexOf(preferredFormat as (typeof LADDER_STEPS)[number])
    const codecs = videoCodecs ?? []

    const chooseGoal = (next: QualityGoal) => {
        setValue('qualityGoal', next, OPTIONS)
        if (next !== 'custom') {
            const preset = GOAL_PRESETS[next]
            setValue('videoCodecs', preset.videoCodecs.map((choice) => ({...choice})), OPTIONS)
            setValue('container', preset.container, OPTIONS)
            setValue('audioCodec', preset.audioCodec, OPTIONS)
        }
    }
    // Changing a codec, the container or the audio codec while a goal is chosen makes it your own.
    const makeOwn = () => {
        if (goal !== 'custom') setValue('qualityGoal', 'custom', OPTIONS)
    }
    const setCodecs = (next: CodecChoice[]) => {
        setValue('videoCodecs', next, OPTIONS)
        makeOwn()
    }
    const move = (from: number, to: number) => {
        if (to < 0 || to >= codecs.length || from === to) return
        const next = [...codecs]
        const [item] = next.splice(from, 1)
        next.splice(to, 0, item)
        setCodecs(next)
    }

    const step = (value: string, label: string, included: boolean) => (
        <button
            key={value} type="button" role="radio" aria-checked={preferredFormat === value}
            className={`quality-ladder__step${preferredFormat === value ? ' is-selected' : included ? ' is-included' : ''}`}
            onClick={() => setValue('preferredFormat', value, OPTIONS)}
        >
            {label}
        </button>
    )

    return (
        <div className="form-row quality-field">
            <span className="quality-field__label" id="quality-up-to">Up to</span>
            <div className="quality-ladder" role="radiogroup" aria-labelledby="quality-up-to">
                {LADDER_STEPS.map((value, index) => step(value, PreferredFormatReg.getLabel(value), chosenIndex >= 0 && index < chosenIndex))}
                {allowAudioOnly && step('format_audio_only', 'Audio only', false)}
                {allowHls && step('format_hls', 'HLS', false)}
            </div>
            <div className="help">
                {audioOnly
                    ? 'Audio only: no video is downloaded.'
                    : hls
                        ? 'An HLS bundle keeps The Daily Wire’s 480p, 720p and 1080p versions together. Only for The Daily Wire.'
                        : 'VODLoft downloads the highest resolution the site has up to this, and falls back to the highlighted ones.'}
            </div>
            {errors.preferredFormat && <div className="error" role="alert">{String(errors.preferredFormat.message)}</div>}

            {audioOnly && (
                <>
                    <span className="quality-field__label" id="quality-audio-format">Audio format</span>
                    <div className="quality-cards" role="radiogroup" aria-labelledby="quality-audio-format">
                        {AudioFormatReg.values.map((value) => (
                            <button
                                key={value} type="button" role="radio" aria-checked={audioFormat === value}
                                className={`quality-card${audioFormat === value ? ' is-selected' : ''}`}
                                onClick={() => setValue('audioFormat', value, OPTIONS)}
                            >
                                <strong>{AudioFormatReg.getLabel(value)}</strong>
                                <span>{AudioFormatReg.getHelp(value)}</span>
                            </button>
                        ))}
                    </div>
                    <div className="help">Podcast RSS feeds use this format.</div>
                </>
            )}

            {!audioOnly && !hls && (
                <>
                    <span className="quality-field__label" id="quality-goal">Optimise for</span>
                    <div className="quality-cards" role="radiogroup" aria-labelledby="quality-goal">
                        {QualityGoalReg.values.map((value) => (
                            <button
                                key={value} type="button" role="radio" aria-checked={goal === value}
                                className={`quality-card${goal === value ? ' is-selected' : ''}`}
                                onClick={() => chooseGoal(value)}
                            >
                                <strong>{QualityGoalReg.getLabel(value)}</strong>
                                <span>{value === 'custom' && goal === 'custom' ? codecSummary(codecs, container) : QualityGoalReg.getHelp(value)}</span>
                            </button>
                        ))}
                    </div>

                    {goal === 'custom' && (
                        <div className="quality-own">
                            <div>
                                <span className="quality-field__label">Video codecs</span>
                                <div className="help">Drag to set the order. Switched off means never.</div>
                            </div>
                            <ol className="quality-codecs">
                                {codecs.map((choice, index) => (
                                    <li
                                        key={choice.codec}
                                        className={`quality-codec${choice.allowed ? '' : ' is-off'}${dragging === index ? ' is-dragging' : ''}`}
                                        draggable
                                        onDragStart={(event) => {
                                            setDragging(index)
                                            event.dataTransfer.effectAllowed = 'move'
                                        }}
                                        onDragOver={(event) => {
                                            event.preventDefault()
                                            if (dragging !== null && dragging !== index) {
                                                move(dragging, index)
                                                setDragging(index)
                                            }
                                        }}
                                        onDragEnd={() => setDragging(null)}
                                    >
                                        <span className="quality-codec__grip" aria-hidden="true">
                                            <FontAwesomeIcon icon={faIcon('fass', 'grip-vertical')}/>
                                        </span>
                                        <span className="quality-codec__text">
                                            <strong>{VideoCodecReg.getLabel(choice.codec)}</strong>
                                            {CODEC_TAGS[choice.codec] && <span className="quality-codec__tag">{CODEC_TAGS[choice.codec]}</span>}
                                            <span className="quality-codec__help">{VideoCodecReg.getHelp(choice.codec)}</span>
                                        </span>
                                        <span className="quality-codec__move">
                                            <button type="button" aria-label={`Move ${VideoCodecReg.getLabel(choice.codec)} up`} disabled={index === 0} onClick={() => move(index, index - 1)}>
                                                <FontAwesomeIcon icon={faIcon('fass', 'chevron-up')}/>
                                            </button>
                                            <button type="button" aria-label={`Move ${VideoCodecReg.getLabel(choice.codec)} down`} disabled={index === codecs.length - 1} onClick={() => move(index, index + 1)}>
                                                <FontAwesomeIcon icon={faIcon('fass', 'chevron-down')}/>
                                            </button>
                                        </span>
                                        <Switch
                                            checked={choice.allowed}
                                            aria-label={`Allow ${VideoCodecReg.getLabel(choice.codec)}`}
                                            onChange={(allowed) => setCodecs(codecs.map((item, i) => i === index ? {...item, allowed} : item))}
                                            onColor="#0ea5e9" offColor="#94a3b8" uncheckedIcon={false} checkedIcon={false}
                                            height={18} width={34} handleDiameter={14}
                                        />
                                    </li>
                                ))}
                            </ol>
                            {errors.videoCodecs && <div className="error" role="alert">{String((errors.videoCodecs as any).message ?? (errors.videoCodecs as any).root?.message ?? 'Allow at least one video codec')}</div>}

                            <span className="quality-field__label">When none of these is available</span>
                            <div className="quality-radios" role="radiogroup">
                                {CodecFallbackReg.values.map((value) => (
                                    <label key={value} className="quality-radio">
                                        <input
                                            type="radio" name="codec-fallback" checked={codecFallback === value}
                                            onChange={() => setValue('codecFallback', value, OPTIONS)}
                                        />
                                        <span>
                                            <strong>{CodecFallbackReg.getLabel(value)}</strong>
                                            {CodecFallbackReg.getHelp(value) && <small>{CodecFallbackReg.getHelp(value)}</small>}
                                        </span>
                                    </label>
                                ))}
                            </div>

                            <div className="quality-own__pair">
                                <div>
                                    <span className="quality-field__label">Container</span>
                                    <SegmentedOptions
                                        name="quality-container" value={container} ariaLabel="Container"
                                        options={ContainerReg.options}
                                        onChange={(value) => {
                                            setValue('container', value, OPTIONS)
                                            makeOwn()
                                        }}
                                    />
                                    <div className="help">MKV holds every codec as is. MP4 plays more widely, but AV1 in MP4 needs a recent player.</div>
                                </div>
                                <div>
                                    <span className="quality-field__label">Audio codec</span>
                                    <SegmentedOptions
                                        name="quality-audio-codec" value={audioCodec} ariaLabel="Audio codec"
                                        options={AudioCodecReg.options}
                                        onChange={(value) => {
                                            setValue('audioCodec', value, OPTIONS)
                                            makeOwn()
                                        }}
                                    />
                                    <div className="help">Opus is smaller. AAC plays on older Apple devices.</div>
                                </div>
                            </div>
                            <div className="help">Choosing Compatibility, Quality or Small files again replaces this order with that goal’s.</div>
                        </div>
                    )}
                </>
            )}

            {!hls && (
                <div className="quality-field__language">
                    <label className="quality-field__label" htmlFor="quality-audio-language">Audio language</label>
                    <Select
                        inputId="quality-audio-language"
                        classNamePrefix="select"
                        options={AudioLanguageReg.options}
                        value={AudioLanguageReg.options.find((option) => option.value === (audioLanguage ?? 'original')) ?? null}
                        onChange={(option) => setValue('audioLanguage', !option || option.value === 'original' ? null : option.value, OPTIONS)}
                        isSearchable
                    />
                    <div className="help">For videos with dubbed audio tracks. Original keeps the language the video was made in.</div>
                </div>
            )}
            <div className="help">Applies to sites downloaded with yt-dlp. The Daily Wire offers fixed formats.</div>
        </div>
    )
}
