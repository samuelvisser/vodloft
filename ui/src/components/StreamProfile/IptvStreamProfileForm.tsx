import {z} from 'zod'
import {UseFormReturn} from 'react-hook-form'
import {useQuery} from '@tanstack/react-query'
import ReadMore from '../../utils/ReadMore'
import NumberInput from '../common/NumberInput'
import {apiJson, publicAddress} from '../../lib/api'
import StreamAddressField from './StreamAddressField'
import StreamDeliveryFields from './StreamDeliveryFields'

type Props = {
    form: UseFormReturn<any>
    isCreating?: boolean
    /** The channel's own playlist and guide, once it is saved. */
    playlistPath?: string
    guidePath?: string
    onRegenerateToken?: () => void | Promise<void>
    regeneratingToken?: boolean
    /** Whether the collection's Site streams live episodes. */
    liveEpisodes?: boolean
    proxyChoice?: boolean
    siteName?: string
}

/** The settings of a TV channel for IPTV apps, and the addresses an app subscribes to. */
export default function IptvStreamProfileForm({
    form,
    isCreating,
    playlistPath,
    guidePath,
    onRegenerateToken,
    regeneratingToken,
    liveEpisodes = true,
    proxyChoice = false,
    siteName = 'its site',
}: Props) {
    const {formState: {errors}, register, watch} = form
    const preferredFormat: string | undefined = watch('preferredFormat')
    const {data: nextChannelNumber} = useQuery({
        queryKey: ['iptvNextChannelNumber'],
        enabled: !!isCreating,
        queryFn: () => apiJson('/iptv-stream-profiles/next-channel-number', (data) => z.int().parse(data)),
    })

    return (
        <>
            <div className="form-row">
                <label htmlFor="iptv-channel-number">Channel number</label>
                <NumberInput
                    id="iptv-channel-number"
                    inputMode="numeric"
                    min={1}
                    step={1}
                    placeholder={nextChannelNumber ? String(nextChannelNumber) : undefined}
                    {...register('channelNumber', {setValueAs: (value) => (value === '' || value == null ? null : Number(value))})}
                    aria-invalid={!!errors.channelNumber}
                    aria-describedby={errors.channelNumber ? 'iptv-channel-number-error' : 'iptv-channel-number-help'}
                />
                {errors.channelNumber && (
                    <div id="iptv-channel-number-error" className="error" role="alert" aria-live="polite">
                        {String(errors.channelNumber.message)}
                    </div>
                )}
                <div className="help" id="iptv-channel-number-help">
                    Where the channel sits in your TV app&apos;s channel list. Leave it empty for the next free number.
                </div>
            </div>

            <div className="form-row">
                <label htmlFor="iptv-channel-group">Channel group</label>
                <input
                    id="iptv-channel-group"
                    className="input"
                    type="text"
                    placeholder={siteName}
                    {...register('channelGroup', {setValueAs: (value) => (value?.trim() ? value.trim() : null)})}
                    aria-invalid={!!errors.channelGroup}
                    aria-describedby={errors.channelGroup ? 'iptv-channel-group-error' : 'iptv-channel-group-help'}
                />
                {errors.channelGroup && (
                    <div id="iptv-channel-group-error" className="error" role="alert" aria-live="polite">
                        {String(errors.channelGroup.message)}
                    </div>
                )}
                <div className="help" id="iptv-channel-group-help">
                    The group your TV app lists the channel under. Leave it empty to use {siteName}.
                </div>
            </div>

            <StreamDeliveryFields
                form={form}
                app="TV app"
                maxItemsLabel="Maximum episodes in the guide"
                maxItemsHelp={(
                    <ReadMore summary={<span>Only the newest episodes play on the channel and fill its guide.</span>}>
                        <p>
                            The guide shows the last week. Between episodes, the channel plays the newest one it
                            aired again, so the guide never has gaps.
                        </p>
                        <p>Set to 0 to remove all limits.</p>
                    </ReadMore>
                )}
                offersLiveEpisodes={liveEpisodes && preferredFormat !== 'format_audio_only'}
                proxyChoice={proxyChoice}
                siteName={siteName}
            />

            {!isCreating && playlistPath && guidePath && (
                <>
                    <StreamAddressField
                        id="iptv-playlist-url"
                        label="Playlist URL"
                        what="playlist URL"
                        value={publicAddress(playlistPath)}
                        onRegenerate={onRegenerateToken}
                        regenerating={regeneratingToken}
                        help={(
                            <ReadMore summary={<span>Add this M3U playlist to your TV app, such as TiviMate or Kodi&apos;s IPTV Simple.</span>}>
                                <p>
                                    The playlist and guide stay reachable even when you sign in to VODLoft, so your TV
                                    app never needs to. Your account page has one playlist with all your channels.
                                </p>
                                <p>
                                    If an address ever leaks, use <strong>Regenerate</strong> to give this channel new
                                    ones; the old playlist, guide and channel addresses stop working at once.
                                </p>
                            </ReadMore>
                        )}
                    />
                    <StreamAddressField
                        id="iptv-guide-url"
                        label="Guide URL"
                        what="guide URL"
                        value={publicAddress(guidePath)}
                        help="The XMLTV programme guide. Most apps find it in the playlist; add it yourself where an app asks for an EPG address."
                    />
                </>
            )}
        </>
    )
}
