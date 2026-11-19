import {ReactNode, useEffect} from 'react'
import {Controller, UseFormReturn} from 'react-hook-form'
import Select from 'react-select'
import ReadMore from '../../utils/ReadMore'
import {RssHlsOutputModes, RssVideoOutputModeReg} from '../../types/stream_profile'
import StreamAddressField from './StreamAddressField'
import StreamDeliveryFields from './StreamDeliveryFields'


const VIDEO_FORMATS = new Set(['format_4k', 'format_1080p', 'format_720p', 'format_360p', 'format_hls'])

type Props = {
    form: UseFormReturn<any>
    isCreating?: boolean
    onRegenerateToken?: () => void | Promise<void>
    regeneratingToken?: boolean
    advisory?: ReactNode
    /** Whether the collection's Site streams live episodes. */
    liveEpisodes?: boolean
    /** Whether HLS video outputs can be offered: only where the Site streams HLS or Download Profiles can keep it as HLS. */
    hlsVideo?: boolean
    /** Whether a feed can send podcast apps straight to the Site's video, or pass it through VODLoft. */
    proxyChoice?: boolean
    /** What each video output does on the Site, where it differs from the usual explanation. */
    videoOutputHelp?: Record<string, string>
    siteName?: string
}

// The MP4 output that takes the place of an HLS one on a Site that has no HLS video.
const MP4_FOR_HLS: Record<string, string> = {audio_hls: 'audio_mp4', mp4_hls: 'mp4'}

export default function RssStreamProfileForm({
    form,
    isCreating,
    onRegenerateToken,
    regeneratingToken,
    advisory,
    liveEpisodes = true,
    hlsVideo = true,
    proxyChoice = false,
    videoOutputHelp = {},
    siteName = 'its site',
}: Props) {
    const {control, formState: {errors}, register, setValue, watch} = form

    const feedUrl: string | undefined = watch('feedUrl')
    const preferredFormat: string | undefined = watch('preferredFormat')
    const videoOutputMode: string | null | undefined = watch('videoOutputMode')
    const usesVideo = VIDEO_FORMATS.has(preferredFormat ?? '')
    const usesHlsVideo = usesVideo && RssHlsOutputModes.has(videoOutputMode ?? '')

    useEffect(() => {
        if (preferredFormat === 'format_audio_only') {
            if (videoOutputMode !== null) {
                setValue('videoOutputMode', null, {
                    shouldDirty: true,
                    shouldValidate: true,
                })
            }
            return
        }

        if (usesVideo && videoOutputMode == null) {
            setValue('videoOutputMode', hlsVideo ? 'audio_hls' : 'audio_mp4', {
                shouldDirty: true,
                shouldValidate: true,
            })
        } else if (!hlsVideo && videoOutputMode && MP4_FOR_HLS[videoOutputMode]) {
            setValue('videoOutputMode', MP4_FOR_HLS[videoOutputMode], {
                shouldDirty: true,
                shouldValidate: true,
            })
        }
    }, [hlsVideo, preferredFormat, setValue, usesVideo, videoOutputMode])

    return (
        <>
            <StreamDeliveryFields
                form={form}
                app="podcast app"
                maxItemsLabel="Maximum episodes in RSS feed"
                maxItemsHelp={(
                    <ReadMore summary={<span>Include only the newest episodes. Keeping this low speeds up RSS experience.</span>}>
                        <p>
                            Capping the amount of included episodes usually greatly improves the performance of your RSS feed.
                        </p>
                        <p>
                            Set to 0 to remove all limits.
                        </p>
                    </ReadMore>
                )}
                offersLiveEpisodes={liveEpisodes && usesHlsVideo}
                proxyChoice={proxyChoice}
                siteName={siteName}
            >
                {usesVideo && (
                    <div className="form-row">
                        <label htmlFor="rss-video-output-mode">Video podcast output</label>
                        <Controller
                            control={control}
                            name="videoOutputMode"
                            render={({field}) => (
                                <Select
                                    inputId="rss-video-output-mode"
                                    classNamePrefix="select"
                                    options={RssVideoOutputModeReg.options.filter((option) => hlsVideo || !RssHlsOutputModes.has(option.value))}
                                    value={RssVideoOutputModeReg.options.find(option => option.value === field.value) ?? null}
                                    onChange={(option) => field.onChange((option as any)?.value)}
                                    onBlur={field.onBlur}
                                    isClearable={false}
                                    aria-invalid={!!errors.videoOutputMode}
                                    aria-describedby={errors.videoOutputMode ? 'rss-video-output-mode-error' : 'rss-video-output-mode-help'}
                                />
                            )}
                        />
                        {errors.videoOutputMode && (
                            <div id="rss-video-output-mode-error" className="error" role="alert" aria-live="polite">
                                {String(errors.videoOutputMode.message)}
                            </div>
                        )}
                        <div className="help" id="rss-video-output-mode-help">
                            <ReadMore summary={<span>Choose how to serve video in your RSS feed depending on what your podcast player supports.</span>}>
                                {RssVideoOutputModeReg.options
                                    .filter((option) => hlsVideo || !RssHlsOutputModes.has(option.value))
                                    .map((option) => (
                                        <p key={option.value}>
                                            <strong>{option.label}</strong> {videoOutputHelp[option.value] ?? RssVideoOutputModeReg.getHelp(option.value)}
                                        </p>
                                    ))}
                                <p>
                                    The episode URLs in the RSS never change when a local download appears. The same VODLoft URL resolves to local media when available, and streams from the collection's site only when the profile permits that fallback.
                                </p>
                            </ReadMore>
                        </div>
                    </div>
                )}
            </StreamDeliveryFields>

            {advisory}

            {!isCreating && (
                <StreamAddressField
                    id="feed-url"
                    label="RSS feed URL"
                    what="RSS feed URL"
                    value={feedUrl}
                    inputProps={{placeholder: 'https://example.com/feed.xml', ...register('feedUrl')}}
                    onRegenerate={onRegenerateToken}
                    regenerating={regeneratingToken}
                    error={errors.feedUrl ? String(errors.feedUrl.message) : undefined}
                    help={(
                        <ReadMore summary={<span>Paste this URL into your podcast app.</span>}>
                            <p>
                                This feed stays reachable even when local authentication is enabled for the VODLoft UI, so your podcast app never needs to log in. You can freely edit this text, for example to use a different hostname.
                            </p>
                            <p>
                                If this URL ever leaks, use <strong>Regenerate</strong> to mint a new one and immediately invalidate the old one.
                            </p>
                        </ReadMore>
                    )}
                />
            )}
        </>
    )
}
