import {useEffect, useMemo, useState} from 'react'
import {useWatch, type UseFormReturn} from 'react-hook-form'
import Select from '../../components/common/Select'
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
    PreferredFormatReg,
    offersFormat,
    profileDownloadOptions,
    profileSitesOffering,
    siteNames,
    type LocalMediaProfileType,
} from '../../types/local_media_profile'
import RequestedField from '../common/RequestedField'
import {KEEPS_TRACKS_REASON, NO_TRACKS_REASON, switchProfileKind, useTracksLock} from './musicKind'
import {useProfileFit} from './ProfileFit'
import './QualityField.css'

type Props = {
    form: UseFormReturn<any>
    mode: LocalMediaProfileType
    isCreating: boolean
}

const OPTIONS = {shouldDirty: true, shouldValidate: true} as const

type DownloadOption = {value: string; label: string}

/**
 * Quality: what to download (video up to a resolution, audio only or HLS), a goal, and your own codec order.
 * Only what the profile's Sites offer is shown; each Site gets the nearest it has.
 */
export default function QualityField({form, mode, isCreating}: Props) {
    const {control, setValue, formState: {errors}} = form
    // A link from a Download Profile can ask for the format its Stream Profile streams.
    const fit = useProfileFit(mode)
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

    // A new download can change what a profile for Music keeps: tracks or music videos.
    const chooseFormat = (next: string) => {
        const scope = form.getValues('collectionScope') as string | undefined
        const previous = form.getValues('preferredFormat') as string | undefined
        setValue('preferredFormat', next, OPTIONS)
        if (mode !== 'collection') return ['preferredFormat']
        return ['preferredFormat', ...switchProfileKind(form, {scope, format: previous}, {scope, format: next}, isCreating)]
    }
    // Choosing fewer Sources can take away the chosen download; move to the nearest one they offer.
    useEffect(() => {
        if (!offered || !preferredFormat || offersFormat(offered, preferredFormat)) return
        // Sites with sound only offer no video to move to, only the sound.
        const nearest = nearestVideoFormat(offered, preferredFormat) ?? (offered.audioOnly ? 'format_audio_only' : undefined)
        if (nearest) chooseFormat(nearest)
        // chooseFormat only reads the form, so a new one each render needs no new run.
    }, [offered, preferredFormat])
    const collectionScope = useWatch({control, name: 'collectionScope'}) as string | undefined
    const music = mode === 'collection' && collectionScope === 'music'
    // An HLS bundle lets podcast apps switch resolutions; a profile for Music keeps tracks or music videos, so moving
    // to Music takes the nearest plain video instead.
    useEffect(() => {
        if (!music || preferredFormat !== 'format_hls') return
        chooseFormat((offered && nearestVideoFormat(offered, preferredFormat)) ?? 'format_1080p')
        // chooseFormat only reads the form, so a new one each render needs no new run.
    }, [music, preferredFormat, offered])
    // A profile for Music keeps tracks when it downloads audio only, so with downloads it stays on one side of that.
    const {hasDownloads, savedTracks} = useTracksLock(form, isCreating)
    const tracksLocked = music && hasDownloads && savedTracks
    const tracksBlocked = music && hasDownloads && !savedTracks
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

    // A profile for Music that downloads video keeps music videos.
    const videoUpTo = music ? 'Music video, up to' : 'Video, up to'
    const option = (value: string): DownloadOption => ({value, label: QualityDownloadReg.getLabelLoose(value)})
    const downloadGroups = tracksLocked ? [{label: 'Music', options: [option('format_audio_only')]}] : [
        {
            label: videoUpTo,
            options: LADDER_STEPS.filter((step) => !offered || offered.videoHeights.includes(FORMAT_HEIGHTS[step])).map(option),
        },
        {
            label: 'Other',
            options: [
                ...(!offered || offered.audioOnly ? [option('format_audio_only')] : []),
                // Only episodes of podcasts and series are kept as an HLS bundle, for podcast feeds.
                ...(mode === 'collection' && !music && offered?.hlsBundle ? [option('format_hls')] : []),
            ],
        },
    ].filter((group) => group.options.length)
    const downloadValue = downloadGroups.flatMap((group) => group.options).find((choice) => choice.value === preferredFormat) ?? null
    const isLadderStep = (value: string) => (LADDER_STEPS as readonly string[]).includes(value)

    return (
        <div className="quality-field">
            <div className="form-row">
                <label htmlFor="quality-download">Download</label>
                <RequestedField
                    id="preferredFormat"
                    requested={fit.format}
                    value={preferredFormat}
                    fields={['preferredFormat']}
                    apply={() => chooseFormat(fit.format!)}
                    fits={() => preferredFormat === fit.format}
                    incompatible={fit.format && <>
                        This profile no longer downloads {PreferredFormatReg.getLabelLoose(fit.format)}, the format the
                        link you followed asked for.
                    </>}
                >
                <Select<DownloadOption>
                    inputId="quality-download"
                    options={downloadGroups}
                    value={downloadValue}
                    onChange={(choice) => choice && chooseFormat(choice.value)}
                    isOptionDisabled={(choice) => tracksBlocked && choice.value === 'format_audio_only'}
                    formatOptionLabel={(choice, {context}) => {
                        if (isLadderStep(choice.value)) return context === 'value' ? `${videoUpTo} ${choice.label}` : choice.label
                        // A profile for Music keeps tracks, not podcasts, when it downloads audio only, and music videos
                        // otherwise.
                        const help = !music ? QualityDownloadReg.getHelp(choice.value as any)
                            : choice.value === 'format_audio_only' ? 'No video, kept as tracks with music tags'
                            : choice.value === 'format_hls' ? QualityDownloadReg.getHelp(choice.value as any)
                            : undefined
                        return context === 'menu' && help
                            ? <span className="quality-download-option">{choice.label}<small>{help}</small></span>
                            : choice.label
                    }}
                    isSearchable={false}
                    aria-invalid={!!errors.preferredFormat}
                />
                </RequestedField>
                {errors.preferredFormat && <div className="error" role="alert">{String(errors.preferredFormat.message)}</div>}
                <div className="help">
                    {tracksLocked
                        ? KEEPS_TRACKS_REASON
                        : tracksBlocked && !audioOnly
                        ? NO_TRACKS_REASON
                        : music && audioOnly
                        ? 'Audio only: tracks, with the artist, album and track number music players read.'
                        : music && !hls
                        ? 'Music videos, with a musicvideo NFO. VODLoft downloads the highest resolution the site has up to this, and falls back to lower ones.'
                        : audioOnly
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
                                {AudioFormatReg.values.filter((value) => music || value !== 'flac').map((value) => (
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
                            <div className="help">{music ? 'Music players read the tags and cover art of M4A, MP3 and FLAC; Opus files get tags but no cover art.' : 'Podcast RSS feeds use this format.'} {appliesTo}</div>
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
