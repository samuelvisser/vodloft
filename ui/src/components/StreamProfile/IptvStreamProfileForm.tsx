import {z} from 'zod'
import {Controller, UseFormReturn} from 'react-hook-form'
import {useQuery} from '@tanstack/react-query'
import Switch from 'react-switch'
import ReadMore from '../../utils/ReadMore'
import NumberInput from '../common/NumberInput'
import SimpleSelect from '../common/SimpleSelect'
import {apiJson, publicAddress} from '../../lib/api'
import {IptvBetweenLiveEpisodesReg} from '../../types/stream_profile'
import StreamAddressField from './StreamAddressField'
import StreamDeliveryFields from './StreamDeliveryFields'

/** The addresses of a saved channel's own playlists and guide. */
export type IptvAddresses = {
    playlistPath: string
    guidePath: string
    episodesPath: string
}

type Props = {
    form: UseFormReturn<any>
    isCreating?: boolean
    addresses?: IptvAddresses
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
    addresses,
    onRegenerateToken,
    regeneratingToken,
    liveEpisodes = true,
    proxyChoice = false,
    siteName = 'its site',
}: Props) {
    const {control, formState: {errors}, register, watch} = form
    const preferredFormat: string | undefined = watch('preferredFormat')
    const listEpisodes: boolean = watch('listEpisodes')
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

            <div className="form-row">
                <label htmlFor="iptv-between-live-episodes">Between live episodes</label>
                <Controller
                    control={control}
                    name="betweenLiveEpisodes"
                    render={({field}) => (
                        <SimpleSelect
                            inputId="iptv-between-live-episodes"
                            registry={IptvBetweenLiveEpisodesReg}
                            value={field.value}
                            onChange={field.onChange}
                            onBlur={field.onBlur}
                            aria-invalid={!!errors.betweenLiveEpisodes}
                            aria-describedby={errors.betweenLiveEpisodes ? 'iptv-between-live-episodes-error' : 'iptv-between-live-episodes-help'}
                        />
                    )}
                />
                {errors.betweenLiveEpisodes && (
                    <div id="iptv-between-live-episodes-error" className="error" role="alert" aria-live="polite">
                        {String(errors.betweenLiveEpisodes.message)}
                    </div>
                )}
                <div className="help" id="iptv-between-live-episodes-help">
                    <ReadMore summary={<span>What the channel shows when no episode is on.</span>}>
                        {IptvBetweenLiveEpisodesReg.options.map((option) => (
                            <p key={option.value}>
                                <strong>{option.label}</strong> {IptvBetweenLiveEpisodesReg.getHelp(option.value)}
                            </p>
                        ))}
                    </ReadMore>
                </div>
            </div>

            <div className="form-row">
                <label htmlFor="iptv-catch-up-days">Catch-up window in days</label>
                <NumberInput
                        id="iptv-catch-up-days"
                        inputMode="numeric"
                        min={1}
                        max={30}
                        step={1}
                        {...register('catchUpDays', {valueAsNumber: true})}
                        aria-invalid={!!errors.catchUpDays}
                    aria-describedby={errors.catchUpDays ? 'iptv-catch-up-days-error' : 'iptv-catch-up-days-help'}
                />
                {errors.catchUpDays && (
                    <div id="iptv-catch-up-days-error" className="error" role="alert" aria-live="polite">
                        {String(errors.catchUpDays.message)}
                    </div>
                )}
                <div className="help" id="iptv-catch-up-days-help">
                    <ReadMore summary={<span>How far back the guide reaches, from 1 to 30 days.</span>}>
                        <p>
                            TV apps with catch-up, such as TiviMate and Kodi, play an episode again from its place in
                            the guide. Apps without it still show the guide.
                        </p>
                    </ReadMore>
                </div>
            </div>

            <StreamDeliveryFields
                form={form}
                app="TV app"
                maxItemsLabel="Maximum episodes in the guide"
                maxItemsHelp={(
                    <ReadMore summary={<span>Only the newest episodes play on the channel and fill its guide.</span>}>
                        <p>Set to 0 to remove all limits.</p>
                    </ReadMore>
                )}
                offersLiveEpisodes={liveEpisodes && preferredFormat !== 'format_audio_only'}
                proxyChoice={proxyChoice}
                siteName={siteName}
            />

            <div className="form-row">
                <label htmlFor="iptv-list-episodes">Also list episodes on their own</label>
                <Controller
                    control={control}
                    name="listEpisodes"
                    render={({field}) => (
                        <Switch
                            id="iptv-list-episodes"
                            checked={!!field.value}
                            onChange={(checked) => field.onChange(checked)}
                            onColor="#0ea5e9"
                            offColor="#d1d5db"
                            uncheckedIcon={false}
                            checkedIcon={false}
                            aria-describedby="iptv-list-episodes-help"
                        />
                    )}
                />
                <div className="help" id="iptv-list-episodes-help">
                    Adds an episode playlist with every episode as an entry of its own, for apps without a guide,
                    such as VLC.
                </div>
            </div>

            {!isCreating && addresses && (
                <>
                    <StreamAddressField
                        id="iptv-playlist-url"
                        label="Playlist URL"
                        what="playlist URL"
                        value={publicAddress(addresses.playlistPath)}
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
                                    ones; the old playlist, guide, channel and episode addresses stop working at once.
                                </p>
                            </ReadMore>
                        )}
                    />
                    <StreamAddressField
                        id="iptv-guide-url"
                        label="Guide URL"
                        what="guide URL"
                        value={publicAddress(addresses.guidePath)}
                        help="The XMLTV programme guide. Most apps find it in the playlist; add it yourself where an app asks for an EPG address."
                    />
                    {listEpisodes && (
                        <StreamAddressField
                            id="iptv-episodes-url"
                            label="Episode playlist URL"
                            what="episode playlist URL"
                            value={publicAddress(addresses.episodesPath)}
                            help="Open this playlist in VLC or another app to pick an episode yourself. It works once you save."
                        />
                    )}
                </>
            )}
        </>
    )
}
