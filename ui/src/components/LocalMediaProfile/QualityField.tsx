import {useEffect, useMemo, useState} from 'react'
import {useWatch, type UseFormReturn} from 'react-hook-form'
import Select from 'react-select'
import Switch from 'react-switch'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'

import {faIcon} from '../../icons/faIcon'
import {
    AudioCodecReg,
    AudioFormatReg,
    AudioLanguageReg,
    CODEC_TAGS,
    CodecFallbackReg,
    ContainerReg,
    GOAL_PRESETS,
    LADDER_STEPS,
    QualityDownloadReg,
    QualityGoalReg,
    VideoCodecReg,
    codecSummary,
    type CodecChoice,
    type QualityGoal,
} from '../../types/quality'
import SegmentedOptions from '../SegmentedOptions/SegmentedOptions'
import {useLocalMediaProfileSites} from '../../lib/queries'
import {
    FORMAT_HEIGHTS,
    nearestVideoFormat,
    offersFormat,
    profileDownloadOptions,
    profileSitesOffering,
    siteNames,
    type LocalMediaProfileType,
} from '../../types/local_media_profile'
import './QualityField.css'

type Props = {
    form: UseFormReturn<any>
    mode: LocalMediaProfileType
}

const OPTIONS = {shouldDirty: true, shouldValidate: true} as const

type DownloadOption = {value: string; label: string}

/**
 * Quality: what to download (video up to a resolution, audio only or HLS), a goal, and your own codec order.
 * Only what the profile's Sites offer is shown; each Site gets the nearest it has.
 */
export default function QualityField({form, mode}: Props) {
    const {control, setValue, formState: {errors}} = form
    const [preferredFormat, goal, videoCodecs, codecFallback, container, audioCodec, audioFormat, audioLanguage, siteKeys, includeUpcomingSites] = useWatch({
        control,
        name: ['preferredFormat', 'qualityGoal', 'videoCodecs', 'codecFallback', 'container', 'audioCodec', 'audioFormat', 'audioLanguage', 'siteKeys', 'includeUpcomingSites'],
    }) as [string, QualityGoal, CodecChoice[], string, string, string, string, string | null, string[] | null, boolean]
    const [dragging, setDragging] = useState<number | null>(null)
    const {data: sites} = useLocalMediaProfileSites()
    const offered = useMemo(
        () => profileDownloadOptions(sites, mode, siteKeys, includeUpcomingSites),
        [sites, mode, siteKeys, includeUpcomingSites],
    )
    const qualityChoices = offered?.qualityChoices ?? true
    // Which of the profile's Sites the format choices apply to, and which have fixed versions.
    const appliesTo = useMemo(() => {
        const choosing = siteNames(profileSitesOffering(sites, mode, siteKeys, includeUpcomingSites, (options) => options.qualityChoices))
        const fixed = profileSitesOffering(sites, mode, siteKeys, false, (options) => !options.qualityChoices).sites
        if (!choosing) return ''
        return `Applies to ${choosing}.${fixed.length ? ` ${siteNames({sites: fixed, upcoming: false})} ${fixed.length > 1 ? 'have' : 'has'} fixed versions.` : ''}`
    }, [sites, mode, siteKeys, includeUpcomingSites])
    // What each of the profile's Sites keeps in an HLS bundle.
    const hlsHelp = useMemo(() => {
        const {sites: bundled, upcoming} = profileSitesOffering(sites, mode, siteKeys, includeUpcomingSites, (options) => options.hlsBundle)
        const heights = (list: readonly number[]) => siteNames({sites: list.map((height) => ({name: `${height}p`})), upcoming: false})
        return [
            ...bundled.map((site) => `${heights(site.downloadOptions.hlsHeights)} from ${site.name}`),
            ...(upcoming && sites ? [`${heights(sites.upcomingDownloadOptions.hlsHeights)} from upcoming sites that have one`] : []),
        ].join(', ')
    }, [sites, mode, siteKeys, includeUpcomingSites])

    // Choosing fewer Sources can take away the chosen download; move to the nearest one they offer.
    useEffect(() => {
        if (!offered || !preferredFormat || offersFormat(offered, preferredFormat)) return
        const nearest = nearestVideoFormat(offered, preferredFormat)
        if (nearest) setValue('preferredFormat', nearest, OPTIONS)
    }, [offered, preferredFormat, setValue])
    const audioOnly = preferredFormat === 'format_audio_only'
    const hls = preferredFormat === 'format_hls'
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

    const option = (value: string): DownloadOption => ({value, label: QualityDownloadReg.getLabelLoose(value)})
    const downloadGroups = [
        {
            label: 'Video, up to',
            options: LADDER_STEPS.filter((step) => !offered || offered.videoHeights.includes(FORMAT_HEIGHTS[step])).map(option),
        },
        {
            label: 'Other',
            options: [
                // A movie is always kept as a video.
                ...(mode !== 'movie' && (!offered || offered.audioOnly) ? [option('format_audio_only')] : []),
                // Only episodes of a collection are kept as an HLS bundle, for podcast feeds.
                ...(mode === 'collection' && offered?.hlsBundle ? [option('format_hls')] : []),
            ],
        },
    ].filter((group) => group.options.length)
    const downloadValue = downloadGroups.flatMap((group) => group.options).find((choice) => choice.value === preferredFormat) ?? null
    const isLadderStep = (value: string) => (LADDER_STEPS as readonly string[]).includes(value)

    return (
        <div className="quality-field">
            <div className="form-row">
                <label htmlFor="quality-download">Download</label>
                <Select<DownloadOption, false>
                    inputId="quality-download"
                    classNamePrefix="select"
                    options={downloadGroups}
                    value={downloadValue}
                    onChange={(choice) => choice && setValue('preferredFormat', choice.value, OPTIONS)}
                    formatOptionLabel={(choice, {context}) => {
                        if (isLadderStep(choice.value)) return context === 'value' ? `Video, up to ${choice.label}` : choice.label
                        const help = QualityDownloadReg.getHelp(choice.value as any)
                        return context === 'menu' && help
                            ? <span className="quality-download-option">{choice.label}<small>{help}</small></span>
                            : choice.label
                    }}
                    isSearchable={false}
                    aria-invalid={!!errors.preferredFormat}
                />
                {errors.preferredFormat && <div className="error" role="alert">{String(errors.preferredFormat.message)}</div>}
                <div className="help">
                    {audioOnly
                        ? 'Audio only: no video is downloaded.'
                        : hls
                            ? `An HLS bundle keeps several resolutions together, so podcast apps can pick one${hlsHelp ? `: ${hlsHelp}` : ''}.`
                            : 'VODLoft downloads the highest resolution the site has up to this, and falls back to lower ones.'}
                </div>
            </div>

            {qualityChoices && !hls && (
                <>
                    {audioOnly && (
                        <div className="form-row">
                            <span className="quality-field__heading" id="quality-audio-format">Audio format</span>
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
                            <div className="help">Podcast RSS feeds use this format. {appliesTo}</div>
                        </div>
                    )}

                    {!audioOnly && (
                        <div className="form-row">
                            <span className="quality-field__heading" id="quality-goal">Optimise for</span>
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
                            {appliesTo && <div className="help">{appliesTo}</div>}

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
                        </div>
                    )}

                    <div className="form-row">
                        <label htmlFor="quality-audio-language">Audio language</label>
                        <Select
                            inputId="quality-audio-language"
                            classNamePrefix="select"
                            options={AudioLanguageReg.options}
                            value={AudioLanguageReg.options.find((option) => option.value === (audioLanguage ?? 'original')) ?? null}
                            onChange={(option) => setValue('audioLanguage', !option || option.value === 'original' ? null : option.value, OPTIONS)}
                            isSearchable
                        />
                        <div className="help">For videos with dubbed audio tracks. Original keeps the language the video was made in. {appliesTo}</div>
                    </div>
                </>
            )}
        </div>
    )
}
