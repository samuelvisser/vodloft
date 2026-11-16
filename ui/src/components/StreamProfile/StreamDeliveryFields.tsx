import {ReactNode, useEffect} from 'react'
import {Controller, UseFormReturn} from 'react-hook-form'
import Switch from 'react-switch'
import ReadMore from '../../utils/ReadMore'
import NumberInput from '../common/NumberInput'

const VIDEO_FORMATS = new Set(['format_4k', 'format_1080p', 'format_720p', 'format_360p', 'format_hls'])

type Props = {
    form: UseFormReturn<any>
    /** The app the profile is for, as the help text names it, such as "podcast app". */
    app: string
    maxItemsLabel: string
    maxItemsHelp: ReactNode
    /** Whether the profile can play live episodes: the Site streams them and the profile serves HLS video. */
    offersLiveEpisodes: boolean
    /** Whether the profile can send apps straight to the Site's video, or pass it through VODLoft. */
    proxyChoice: boolean
    siteName: string
    /** Fields of the profile's own type, shown between the episode limit and the Site's stream. */
    children?: ReactNode
}

/** How every stream profile type delivers its episodes: how many, through VODLoft or not, and live ones. */
export default function StreamDeliveryFields({
    form,
    app,
    maxItemsLabel,
    maxItemsHelp,
    offersLiveEpisodes,
    proxyChoice,
    siteName,
    children,
}: Props) {
    const {control, formState: {errors}, register, setValue, watch} = form
    const useSourceStream: boolean = watch('useSourceStream')
    const preferredFormat: string | undefined = watch('preferredFormat')
    const streamLiveEpisodes: boolean = watch('streamLiveEpisodes')
    const usesVideo = VIDEO_FORMATS.has(preferredFormat ?? '')

    useEffect(() => {
        if (!offersLiveEpisodes && streamLiveEpisodes) {
            setValue('streamLiveEpisodes', false, {
                shouldDirty: true,
                shouldValidate: true,
            })
        }
    }, [offersLiveEpisodes, setValue, streamLiveEpisodes])

    return (
        <>
            <div className="form-row">
                <label htmlFor="stream-max-items">{maxItemsLabel}</label>
                <NumberInput
                    id="stream-max-items"
                    inputMode="numeric"
                    min={0}
                    step={1}
                    {...register('maxItems', {valueAsNumber: true})}
                    aria-invalid={!!errors.maxItems}
                    aria-describedby={errors.maxItems ? 'stream-max-items-error' : 'stream-max-items-help'}
                />
                {errors.maxItems && (
                    <div id="stream-max-items-error" className="error" role="alert" aria-live="polite">
                        {String(errors.maxItems.message)}
                    </div>
                )}
                <div className="help" id="stream-max-items-help">{maxItemsHelp}</div>
            </div>

            {children}

            {usesVideo && proxyChoice && useSourceStream && (
                <div className="form-row">
                    <label htmlFor="stream-proxy-source-stream">Proxy video through VODLoft</label>
                    <Controller
                        control={control}
                        name="proxySourceStream"
                        render={({field}) => (
                            <Switch
                                id="stream-proxy-source-stream"
                                checked={!!field.value}
                                onChange={(checked) => field.onChange(checked)}
                                onColor="#0ea5e9"
                                offColor="#d1d5db"
                                uncheckedIcon={false}
                                checkedIcon={false}
                                aria-invalid={!!errors.proxySourceStream}
                                aria-describedby={errors.proxySourceStream ? 'stream-proxy-source-stream-error' : 'stream-proxy-source-stream-help'}
                            />
                        )}
                    />
                    {errors.proxySourceStream && (
                        <div id="stream-proxy-source-stream-error" className="error" role="alert" aria-live="polite">
                            {String(errors.proxySourceStream.message)}
                        </div>
                    )}
                    <div className="help" id="stream-proxy-source-stream-help">
                        <ReadMore summary={<span>Pass video from {siteName} through VODLoft, instead of letting your {app} fetch it straight from {siteName}.</span>}>
                            <p>
                                This is on by default, because it plays most reliably: when {siteName} refuses a link, VODLoft
                                looks the video up again before your {app} notices. It does add bandwidth overhead: every
                                video you watch is downloaded by your VODLoft server and uploaded again to your {app}.
                            </p>
                            <p>
                                When it is off, your {app} still asks VODLoft for each part of the video, and VODLoft
                                sends it on to {siteName} with a link that has not expired yet. The video itself then comes
                                straight from {siteName}.
                            </p>
                            <p>
                                This only applies to video streamed from {siteName}. Downloaded video always comes from VODLoft.
                            </p>
                        </ReadMore>
                    </div>
                </div>
            )}

            {offersLiveEpisodes && (
                <div className="form-row">
                    <label htmlFor="stream-live-episodes">Stream live episodes</label>
                    <Controller
                        control={control}
                        name="streamLiveEpisodes"
                        render={({field}) => (
                            <Switch
                                id="stream-live-episodes"
                                checked={!!field.value}
                                onChange={(checked) => field.onChange(checked)}
                                onColor="#0ea5e9"
                                offColor="#d1d5db"
                                uncheckedIcon={false}
                                checkedIcon={false}
                                aria-invalid={!!errors.streamLiveEpisodes}
                                aria-describedby={errors.streamLiveEpisodes ? 'stream-live-episodes-error' : 'stream-live-episodes-help'}
                            />
                        )}
                    />
                    {errors.streamLiveEpisodes && (
                        <div id="stream-live-episodes-error" className="error" role="alert" aria-live="polite">
                            {String(errors.streamLiveEpisodes.message)}
                        </div>
                    )}
                    <div className="help" id="stream-live-episodes-help">
                        <ReadMore summary={<span>Include matching episodes while they are live.</span>}>
                            <p>
                                With this setting enabled, you can view even episodes that are currently live at {siteName} straight in your {app}!
                            </p>
                            <p>
                                Live episodes still have to match this Stream Profile&apos;s episode-type filter in order to show up.
                            </p>
                            {!useSourceStream && (
                                <>
                                    <p>
                                        Even though streaming from {siteName} is disabled for this stream profile, streaming live episodes from {siteName}
                                        still works. VODLoft even provides a clean handoff to the downloaded HLS file after the episode is no longer
                                        live: it waits for the download to finish first, and only then switches to streaming from your local file.
                                        Your {app} should not even notice this switch!
                                    </p>
                                    <p>
                                        <strong>Note:</strong> The profile does check whether the episode in question, when no longer live, will be
                                        downloaded by your download profiles as HLS. If not, the episode is not considered part of this
                                        downloads-only profile and will also not be included as a live episode.
                                    </p>
                                </>
                            )}
                            <p>
                                <strong>Note:</strong> live video only works if your {app} supports playing HLS video.
                                A live episode has no length yet, so your {app} may show its progress oddly.
                            </p>
                        </ReadMore>
                    </div>
                </div>
            )}
        </>
    )
}
