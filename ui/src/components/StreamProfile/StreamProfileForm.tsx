import {useEffect, useMemo, useRef} from 'react'
import {Controller, UseFormReturn} from 'react-hook-form'
import Switch from 'react-switch'
import Select from 'react-select'
import ReadMore from '../../utils/ReadMore'
import {episodeTagLabel, SourceFeature, sourceHas} from '../../types/schemas/source'
import {FORMAT_HEIGHTS, PreferredFormatReg} from '../../types/local_media_profile'
import RssStreamProfileForm from './RssStreamProfileForm'
import StreamProfileAdvisory, {type StreamDownloadProfileDefault} from './StreamProfileAdvisory'
import SegmentedOptions from '../SegmentedOptions/SegmentedOptions'
import {MediaTypeReg} from "../../types/stream_profile";
import {createSelectRegistry} from '../../utils/selectRegistry'
import {useCollectionEpisodeTags, useCollections, useSiteOptions, useSourceLookup} from '../../lib/queries'

export type StreamProfileMode = 'rss' | 'base'

export type {StreamDownloadProfileDefault} from './StreamProfileAdvisory'

type UIOption = { value: string; label: string }

const STANDARD_VIDEO_FORMATS = new Set(['format_4k', 'format_1080p', 'format_720p', 'format_360p'])
const StreamPreferredFormatReg = createSelectRegistry('StreamPreferredFormat', {
    format_4k: {label: PreferredFormatReg.getLabel('format_4k')},
    format_1080p: {label: PreferredFormatReg.getLabel('format_1080p')},
    format_720p: {label: PreferredFormatReg.getLabel('format_720p')},
    format_360p: {label: PreferredFormatReg.getLabel('format_360p')},
    format_audio_only: {label: PreferredFormatReg.getLabel('format_audio_only')},
})

function sameEpisodeTypes(a: readonly string[], b: readonly string[]) {
    return a.length === b.length && a.every((value) => b.includes(value))
}

type Props = {
    form: UseFormReturn<any>
    mode: StreamProfileMode
    collectionRoot?: boolean
    isCreating?: boolean
    onRegenerateToken?: () => void | Promise<void>
    regeneratingToken?: boolean
    downloadProfileDefaults?: StreamDownloadProfileDefault[]
    episodeTypesManuallyChanged?: boolean
    onEpisodeTypesManuallyChanged?: () => void
    collectionSlug?: string
    collectionTitle?: string
    /** The Source of a collection that is not saved yet. */
    sourceKey?: string
    /** The link of a collection that is not saved yet. */
    collectionUrl?: string
    canOpenDownloadProfiles?: boolean
}

export default function StreamProfileForm({
    form,
    mode,
    collectionRoot,
    isCreating,
    onRegenerateToken,
    regeneratingToken,
    downloadProfileDefaults,
    episodeTypesManuallyChanged,
    onEpisodeTypesManuallyChanged,
    collectionSlug,
    collectionTitle,
    sourceKey,
    collectionUrl,
    canOpenDownloadProfiles = true,
}: Props) {
    const {control, formState: {errors}, getValues, register, setValue, watch} = form
    collectionRoot ??= true

    // Whether a feed can stream depends on the collection's Site, such as YouTube, not on the Source that fetches it.
    // A collection that is not saved yet is told by the link it is added from.
    const {data: collections} = useCollections()
    const sources = useSourceLookup()
    const collection = collectionSlug ? collections?.find((item) => item.slug === collectionSlug) : undefined
    const {data: site} = useSiteOptions({
        sourceKey: collection?.sourceKey ?? sourceKey,
        url: collection?.sharingUrl ?? collectionUrl,
    })
    const streamSourceKnown = !!site
    const streamMethods = site?.streamMethods ?? []
    const canStreamFromSource = streamMethods.length > 0
    const canStreamLiveEpisodes = streamMethods.includes('live')
    const canStreamHls = streamMethods.includes('hls')
    // A Source that streams from the video's page, such as yt-dlp, streams the page's own MP4; others build it from HLS first.
    const streamSource = sources.get(collection?.sourceKey ?? sourceKey ?? '')
    const streamsMp4Directly = !!streamSource && sourceHas(streamSource, SourceFeature.PAGE_STREAMS)
    const streamSourceName = site?.siteName ?? (collection ? sources.name(collection.sourceKey) : 'its site')

    const useDownloads = watch('useDownloads')
    const useSourceStream = watch('useSourceStream')
    // A feed serves the downloaded version nearest to its format, or the Site's own stream, which only
    // comes in the resolutions the Site streams.
    const videoHeights = site
        ? (canStreamFromSource && useSourceStream && site.streamVideoHeights.length > 0
            ? site.streamVideoHeights
            : site.downloads.videoHeights)
        : undefined
    const preferredFormat = watch('preferredFormat')
    const videoOutputMode = watch('videoOutputMode')
    const streamLiveEpisodes = watch('streamLiveEpisodes')
    const selectedEpisodeTypes: string[] = watch('epIdTypeList') || []
    const {data: tags} = useCollectionEpisodeTags({collectionSlug, sourceKey})
    const tagOptions: UIOption[] = useMemo(() => (tags ?? []).map((tag) => ({value: tag.key, label: tag.label})), [tags])
    const internalEpisodeTypesManuallyChanged = useRef(false)
    const episodeTypeDefaultsInitialized = useRef(false)
    const lastSuggestedTitle = useRef<string | undefined>(undefined)
    const dwStreamClearedForSource = useRef(false)

    // Direct streaming is on by default, but only a Source with RSS streaming can serve it.
    // Turn it off for any other Source, and back on if the form moves to one that can stream.
    useEffect(() => {
        if (!streamSourceKnown) return
        if (!canStreamFromSource && getValues('useSourceStream')) {
            setValue('useSourceStream', false, {shouldDirty: false, shouldValidate: true})
            dwStreamClearedForSource.current = true
        } else if (canStreamFromSource && dwStreamClearedForSource.current) {
            setValue('useSourceStream', true, {shouldDirty: false, shouldValidate: true})
            dwStreamClearedForSource.current = false
        }
    }, [streamSourceKnown, canStreamFromSource, getValues, setValue])

    // Live episodes are only offered where the Site streams them, so a profile never keeps the setting elsewhere.
    useEffect(() => {
        if (streamSourceKnown && !canStreamLiveEpisodes && getValues('streamLiveEpisodes')) {
            setValue('streamLiveEpisodes', false, {shouldDirty: false, shouldValidate: true})
        }
    }, [streamSourceKnown, canStreamLiveEpisodes, getValues, setValue])

    useEffect(() => {
        if (!collectionTitle) return

        const currentTitle = (getValues('title') || '') as string
        const previousSuggestedTitle = lastSuggestedTitle.current
        if (!currentTitle || currentTitle === previousSuggestedTitle) {
            setValue('title', collectionTitle, {
                shouldDirty: false,
                shouldValidate: true,
            })
        }
        lastSuggestedTitle.current = collectionTitle
    }, [getValues, setValue, collectionTitle])

    const selectedSources = [
        ...(useDownloads ? ['downloads'] as const : []),
        ...(useSourceStream ? ['dw'] as const : []),
    ]

    const episodeTypeSelectValue: UIOption[] = useMemo(() => (
        selectedEpisodeTypes.map((value) => ({
            value,
            label: episodeTagLabel(tags, value),
        }))
    ), [selectedEpisodeTypes, tags])

    const automaticEpisodeTypes = useMemo(() => {
        if (useDownloads && downloadProfileDefaults) {
            const candidates = [...downloadProfileDefaults]
                .filter((profile) => profile.enabled !== false)
                .sort((a, b) => Number(Boolean(b.enabled)) - Number(Boolean(a.enabled)))

            const matchingProfile = videoOutputMode === 'audio_hls'
                ? candidates.find((profile) => profile.preferredFormat === 'format_hls')
                : videoOutputMode === 'audio_mp4'
                    ? candidates.find((profile) => STANDARD_VIDEO_FORMATS.has(profile.preferredFormat))
                    : candidates.find((profile) => profile.preferredFormat === preferredFormat)

            if (matchingProfile) return [...(matchingProfile.episodeTypes ?? (tags ?? []).map((tag) => tag.key))]
        }
        return (tags ?? []).filter((tag) => tag.selectedByDefault).map((tag) => tag.key)
    }, [downloadProfileDefaults, preferredFormat, tags, useDownloads, videoOutputMode])

    const episodeTypeDefaultsReady = tags !== undefined && (!useDownloads || downloadProfileDefaults !== undefined)

    useEffect(() => {
        if (!episodeTypeDefaultsReady || !preferredFormat) return

        const current = (getValues('epIdTypeList') || []) as string[]
        const manuallyChanged = episodeTypesManuallyChanged === true
            || internalEpisodeTypesManuallyChanged.current

        if (!episodeTypeDefaultsInitialized.current) {
            episodeTypeDefaultsInitialized.current = true
            if (!isCreating && !manuallyChanged && !sameEpisodeTypes(current, automaticEpisodeTypes)) {
                internalEpisodeTypesManuallyChanged.current = true
                return
            }
        }

        if (
            episodeTypesManuallyChanged !== true
            && !internalEpisodeTypesManuallyChanged.current
            && !sameEpisodeTypes(current, automaticEpisodeTypes)
        ) {
            setValue('epIdTypeList', automaticEpisodeTypes, {
                shouldDirty: false,
                shouldValidate: true,
            })
        }
    }, [
        automaticEpisodeTypes,
        episodeTypeDefaultsReady,
        episodeTypesManuallyChanged,
        getValues,
        isCreating,
        preferredFormat,
        setValue,
    ])

    const markEpisodeTypesManuallyChanged = () => {
        internalEpisodeTypesManuallyChanged.current = true
        if (episodeTypesManuallyChanged !== true) {
            onEpisodeTypesManuallyChanged?.()
        }
    }

    const handleEpisodeTypeChange = (options: readonly UIOption[] | null) => {
        const values = (Array.isArray(options) ? options : []).map((option) => option.value)
        if (!sameEpisodeTypes(values, selectedEpisodeTypes)) {
            markEpisodeTypesManuallyChanged()
        }
        setValue('epIdTypeList', values, {shouldDirty: true, shouldValidate: true})
    }

    const handleSelectAllEpisodeTypes = () => {
        const values = tagOptions.map((option) => option.value)
        if (!sameEpisodeTypes(values, selectedEpisodeTypes)) {
            markEpisodeTypesManuallyChanged()
        }
        setValue('epIdTypeList', values, {shouldDirty: true, shouldValidate: true})
    }

    const streamProfileAdvisory = mode === 'rss' ? (
        <StreamProfileAdvisory
            mode={mode}
            preferredFormat={preferredFormat}
            videoOutputMode={videoOutputMode}
            useDownloads={!!useDownloads}
            useSourceStream={!!useSourceStream}
            streamsMp4Directly={streamsMp4Directly}
            streamLiveEpisodes={!!streamLiveEpisodes}
            selectedEpisodeTypes={selectedEpisodeTypes}
            downloadProfileDefaults={downloadProfileDefaults}
            collectionSlug={collectionSlug}
            canOpenDownloadProfiles={canOpenDownloadProfiles}
            sourceName={streamSourceName}
            canStreamFromSource={canStreamFromSource}
            hlsDownloads={site ? site.downloads.hlsBundle : true}
            onEnableSourceStream={() => setValue('useSourceStream', true, {
                shouldDirty: true,
                shouldValidate: true,
            })}
            onEnableDownloads={() => setValue('useDownloads', true, {
                shouldDirty: true,
                shouldValidate: true,
            })}
            onDisableDwStream={() => setValue('useSourceStream', false, {
                shouldDirty: true,
                shouldValidate: true,
            })}
        />
    ) : null

    return (
        <>
            {collectionRoot && errors.root && (
                <div className="form-error-card" role="alert" aria-live="polite">
                    {String(errors.root.message)}
                </div>
            )}

            <div className="form-row">
                <label htmlFor="stream-profile-title">Title</label>
                <input
                    id="stream-profile-title"
                    className="input"
                    type="text"
                    {...register('title')}
                    aria-invalid={!!errors.title}
                    aria-describedby={errors.title ? 'stream-profile-title-error' : undefined}
                />
                {errors.title && (
                    <div id="stream-profile-title-error" className="error" role="alert" aria-live="polite">
                        {String(errors.title.message)}
                    </div>
                )}
            </div>

            <div className="form-row">
                <label id="stream-sources-label">Streaming sources</label>
                <SegmentedOptions
                    name="stream-sources"
                    multiple
                    ariaLabelledBy="stream-sources-label"
                    options={[
                        {
                            value: 'downloads',
                            label: 'Use Downloads',
                            description: (
                                <ReadMore summary={<span>Stream downloaded media when available.</span>}>
                                    <p>If enabled, downloaded media within VODLoft can be used when streaming.</p>
                                    <p>Streaming downloaded media usually improves the stability of the stream
                                        and ensures a consistent experience.</p>
                                </ReadMore>
                            ),
                        },
                        ...(canStreamFromSource ? [{
                            value: 'dw',
                            label: `Use ${streamSourceName} stream`,
                            description: (
                                <ReadMore summary={<span>Stream episodes straight from {streamSourceName}.</span>}>
                                    <p>
                                        If enabled, VODLoft can stream episodes straight from {streamSourceName},
                                        without downloading them first.
                                    </p>
                                    <p>
                                        If Use Downloads is enabled too, VODLoft will prefer downloaded media,
                                        but stream directly when no downloaded media exists.
                                    </p>
                                    <p>
                                        This could come in handy if you only intend to download a few of the latest episodes,
                                    but still want to retain the ability to stream many more.
                                    </p>
                                    {streamSourceName == 'YouTube' ? (
                                        <p>
                                            YouTube streams video at up to 1080p. As an MP4, it plays at 360p until VODLoft has
                                            prepared the higher quality, which it starts for the newest episodes as soon as your
                                            podcast app fetches the feed.
                                        </p>
                                    ) : null}
                                </ReadMore>
                            ),
                        }] : []),
                    ]}
                    value={selectedSources}
                    onChange={(vals) => {
                        const arr = Array.isArray(vals) ? vals : [vals]
                        const nextUseDownloads = arr.includes('downloads')
                        const nextUseDwStream = arr.includes('dw')
                        setValue('useDownloads', nextUseDownloads, {shouldDirty: true, shouldValidate: true})
                        setValue('useSourceStream', nextUseDwStream, {shouldDirty: true, shouldValidate: true})
                    }}
                />
            </div>

            <div className="form-row">
                <label htmlFor="enable-profile">Enable streaming</label>
                <Controller
                    control={control}
                    name="enableProfile"
                    render={({field}) => (
                        <Switch
                            id="enable-profile"
                            checked={!!field.value}
                            onChange={(checked) => field.onChange(checked)}
                            onColor="#0ea5e9"
                            offColor="#d1d5db"
                            uncheckedIcon={false}
                            checkedIcon={false}
                            aria-invalid={!!errors.enableProfile}
                            aria-describedby={errors.enableProfile ? 'enable-profile-errors' : 'enable-profile-help'}
                        />
                    )}
                />
                {errors.enableProfile && (
                    <div id="enable-profile-errors" className="error" role="alert" aria-live="polite">
                        {String(errors.enableProfile.message)}
                    </div>
                )}
                <div className="help" id="enable-profile-help">
                    <ReadMore summary={<span>Enable streaming the content from VODLoft.</span>}>
                        <p>When enabled, this stream profile will do its job and open your chosen stream (for now, RSS).</p>
                        <p>You can disable it if you want to retain all the stream profile settings but for whatever reason do not want
                            the streaming enabled.</p>
                    </ReadMore>
                </div>
            </div>

            {useDownloads ? (
                <div className="form-row">
                    <label htmlFor="sp-preferred-format">Preferred format</label>
                    <Controller
                        control={control}
                        name="preferredFormat"
                        render={({field}) => (
                            <Select
                                inputId="sp-preferred-format"
                                classNamePrefix="select"
                                options={StreamPreferredFormatReg.options.filter((option) => (
                                    !videoHeights || !(option.value in FORMAT_HEIGHTS) || videoHeights.includes(FORMAT_HEIGHTS[option.value])
                                ))}
                                value={StreamPreferredFormatReg.options.find(o => o.value === field.value) ?? null}
                                onChange={(opt) => field.onChange((opt as any)?.value ?? null)}
                                onBlur={field.onBlur}
                                aria-invalid={!!errors.preferredFormat}
                                aria-describedby={errors.preferredFormat ? 'sp-pref-format-error' : 'sp-pref-format-help'}
                                isClearable
                            />
                        )}
                    />
                    {errors.preferredFormat && (
                        <div id="sp-pref-format-error" className="error" role="alert" aria-live="polite">
                            {String(errors.preferredFormat.message)}
                        </div>
                    )}
                    <div className="help" id="sp-pref-format-help">
                        <ReadMore summary={<span>Content type to prefer while streaming.</span>}>
                            <p>Serves the specified content type if available. If not, it will try to serve the next best option by default.</p>
                            <p>If you need audio-only content, you can set this to 'Audio Only' to stream audio only.</p>
                        </ReadMore>
                    </div>
                </div>
            ) : (
                <div className="form-row">
                    <label htmlFor="sp-preferred-format">Media Type</label>
                    <Controller
                        control={control}
                        name="preferredFormat"
                        render={({field}) => (
                            <Select
                                inputId="sp-preferred-format"
                                classNamePrefix="select"
                                options={MediaTypeReg.options}
                                value={MediaTypeReg.options.find(o => o.value === field.value) ?? null}
                                onChange={(opt) => field.onChange((opt as any)?.value ?? null)}
                                onBlur={field.onBlur}
                                aria-invalid={!!errors.preferredFormat}
                                aria-describedby={errors.preferredFormat ? 'sp-pref-format-error' : 'sp-pref-format-help'}
                                isClearable
                            />
                        )}
                    />
                    {errors.preferredFormat && (
                        <div id="sp-pref-format-error" className="error" role="alert" aria-live="polite">
                            {String(errors.preferredFormat.message)}
                        </div>
                    )}
                    <div className="help" id="sp-pref-format-help">
                        <ReadMore summary={<span>Whether to stream video or audio from {streamSourceName}.</span>}>
                            <p>VODLoft cannot control what format the video or audio that {streamSourceName} provides will be in. Therefore, when Use Downloads
                            is disabled in streaming sources, you cannot select the exact video format you prefer.</p>
                            <p>Setting this to video will set the resolution to 1080p in the background. VODLoft streams the best video
                                {streamSourceName} gives it up to that: YouTube video streams at up to 1080p.</p>
                        </ReadMore>
                    </div>
                </div>
            )}

            <div className="form-row">
                <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
                    <label htmlFor="sp-episode-types">Episode types</label>
                    <button type="button" className="btn btn-link" onClick={handleSelectAllEpisodeTypes}>
                        Select all
                    </button>
                </div>
                <Controller
                    control={control}
                    name="epIdTypeList"
                    render={() => (
                        <Select
                            inputId="sp-episode-types"
                            isMulti
                            options={tagOptions}
                            value={episodeTypeSelectValue}
                            onChange={handleEpisodeTypeChange as any}
                            closeMenuOnSelect={false}
                            getOptionValue={(option: UIOption) => option.value}
                            getOptionLabel={(option: UIOption) => option.label}
                            aria-invalid={!!errors.epIdTypeList}
                            aria-describedby={errors.epIdTypeList ? 'sp-episode-types-error' : 'sp-episode-types-help'}
                        />
                    )}
                />
                {errors.epIdTypeList && (
                    <div id="sp-episode-types-error" className="error" role="alert" aria-live="polite">
                        {String(errors.epIdTypeList.message)}
                    </div>
                )}
                <div className="help" id="sp-episode-types-help">
                    <ReadMore summary={<span>What episode types to stream</span>}>
                        <p>Select all episode types you want this profile to stream.</p>
                        {(tags ?? []).map((tag) => <p key={tag.key}><b>{tag.label}</b>: {tag.help}.</p>)}
                        <p>Until you change this selection manually, VODLoft uses {(tags ?? []).filter((tag) => tag.selectedByDefault).map((tag) => tag.label).join(' and ') || 'the usual types'} by default. When Use Downloads is enabled and a Download Profile for the same collection has the selected Preferred format, its episode types are used as the default instead.</p>
                    </ReadMore>
                </div>
            </div>

            {useDownloads && useSourceStream && STANDARD_VIDEO_FORMATS.has(preferredFormat) && (
                <div className="form-row">
                    <label htmlFor="prefer-exact-match">Prefer Exact Match for Video Downloads</label>
                    <Controller
                        control={control}
                        name="preferExactMatch"
                        render={({field}) => (
                            <Switch
                                id="prefer-exact-match"
                                checked={!!field.value}
                                onChange={(checked) => field.onChange(checked)}
                                onColor="#0ea5e9"
                                offColor="#d1d5db"
                                uncheckedIcon={false}
                                checkedIcon={false}
                                aria-invalid={!!errors.preferExactMatch}
                            />
                        )}
                    />
                    <div className="help">
                        <ReadMore summary={<span>Match downloaded episodes using strict rules.</span>}>
                            <p>
                                When this setting is <strong>enabled</strong>, if say, you have a 720p version downloaded but your preferred format is
                                1080p, instead of using the 720p version, VODLoft will stream from DW directly (in whatever format it happens to provide).<br/>
                                When the setting is <strong>disabled</strong>, it tries to match your preferred format but will stream other video
                                formats from your downloaded files if they are the only ones available locally.
                            </p>
                            <p>
                                Obviously, no matter what this setting is set to, VODLoft will only consider video downloads when trying to match local
                                files to your video streaming request. Audio will never be send in the place of video merely because you had it downloaded.
                            </p>
                            <p>
                                <strong>Note:</strong> VODLoft cannot control what DW provides. This preference only controls whether VODLoft accepts
                                a non-exact local video format before falling back to DW. It does not guarantee that the stream DW provides will be
                                in the exact format you prefer.
                            </p>
                        </ReadMore>
                    </div>
                </div>
            )}

            {mode === 'rss' ? (
                <RssStreamProfileForm
                    form={form}
                    isCreating={isCreating}
                    onRegenerateToken={onRegenerateToken}
                    regeneratingToken={regeneratingToken}
                    advisory={streamProfileAdvisory}
                    liveEpisodes={canStreamLiveEpisodes}
                    hlsVideo={!site || canStreamHls || site.downloads.hlsBundle}
                    proxyChoice={canStreamFromSource && !!site?.streamProxyChoice}
                    siteName={streamSourceName}
                />
            ) : undefined}
        </>
    )
}
