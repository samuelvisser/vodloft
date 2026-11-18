import {useQueryClient} from '@tanstack/react-query'
import {toast} from 'react-hot-toast'
import ConfirmDialog from '../../components/ConfirmDialog/ConfirmDialog'
import {faIcon} from '../../icons/faIcon'
import {setCollectionChannel, useCollectionChannelLeave, useCollectionChannelMatch} from '../../lib/queries'
import type {ChannelLinkMatch} from '../../types/schemas/channel'
import '../channel/ChannelPages.css'

type DialogProps = {
    open: boolean
    collectionSlug: string
    collectionTitle: string
    /** What the collection's Site calls a channel, such as host on The Daily Wire. */
    channelLabel: string
    onDismiss: () => void
}

function useRefresh(collectionSlug: string) {
    const queryClient = useQueryClient()
    return async () => {
        await Promise.all([
            queryClient.invalidateQueries({queryKey: ['collection', collectionSlug]}),
            queryClient.invalidateQueries({queryKey: ['collections']}),
            queryClient.invalidateQueries({queryKey: ['channels']}),
            queryClient.invalidateQueries({queryKey: ['channel']}),
            queryClient.removeQueries({queryKey: ['collection-channel-match', collectionSlug]}),
            queryClient.removeQueries({queryKey: ['collection-channel-leave', collectionSlug]}),
        ])
    }
}

function linkNote(link: ChannelLinkMatch, label: string): string {
    if (link.sectionTitle) {
        const kind = link.sectionKindLabel ? `${link.sectionKindLabel} · ` : ''
        return `${kind}becomes the ${label}'s ${link.sectionTitle} section`
    }
    if (link.keptBy) return `The ${label}'s ${link.keptBy} has this already, so it stays a link of this collection only`
    return `Not part of this ${label}, so it stays a link of this collection only`
}

/** "Add to channel", in the words of the Site: find the channel behind the collection's links, show what each link becomes, and add it. */
export function AddToChannelDialog({open, collectionSlug, collectionTitle, channelLabel, onDismiss}: DialogProps) {
    const match = useCollectionChannelMatch(collectionSlug, open)
    const refresh = useRefresh(collectionSlug)
    const channel = match.data
    const matched = channel?.links.filter((link) => link.sectionTitle).length ?? 0

    const add = async () => {
        if (!channel) return
        try {
            await setCollectionChannel(collectionSlug, true)
            await refresh()
            toast.success(`${collectionTitle} is now part of ${channel.title}`)
            onDismiss()
        } catch (error) {
            toast.error(error instanceof Error ? error.message : `Could not add the collection to the ${channelLabel}`)
        }
    }

    return (
        <ConfirmDialog
            open={open}
            title={`Add ${collectionTitle} to a ${channelLabel}`}
            icon={faIcon('fass', 'circle-user')}
            onDismiss={onDismiss}
            confirmButton={{
                label: channel ? `Add to ${channel.title}` : `Add to ${channelLabel}`,
                onClick: add,
                disabled: !channel || matched === 0,
            }}
        >
            {match.isLoading && <p>Looking up the {channelLabel} behind this collection's links…</p>}
            {match.error && <p className="text-danger">{match.error.message}</p>}
            {channel && (
                <div className="channel-join">
                    <div className="channel-join-who">
                        {channel.avatarUrl
                            ? <img className="channel-avatar channel-avatar--small" src={channel.avatarUrl} alt="" loading="lazy"/>
                            : <span className="channel-avatar channel-avatar--small channel-avatar--empty" aria-hidden="true">{channel.title.slice(0, 1)}</span>}
                        <div className="channel-identity-copy">
                            <span className="channel-kind">{channel.siteName} {channel.channelLabel}</span>
                            <strong>{channel.title}</strong>
                            <span className="channel-section-note">
                                {channel.channelSlug ? 'In your library.' : 'Not in your library yet. It will be added.'}
                            </span>
                        </div>
                    </div>
                    <div className="channel-section-list">
                        {channel.links.map((link) => (
                            <div key={link.url} className="channel-section-row">
                                <div className="channel-section-copy">
                                    <strong>{link.title || (channel.links.length === 1 ? collectionTitle : link.url)}</strong>
                                    <span>{linkNote(link, channelLabel)}</span>
                                </div>
                            </div>
                        ))}
                    </div>
                    {matched === 0
                        ? <p className="channel-order-note">None of this collection's links is a playlist or show of {channel.title} that it does not have yet.</p>
                        : (
                            <ul className="channel-order-note">
                                <li>Seasons, episode numbers, profiles and files stay as they are. Nothing is indexed again.</li>
                                {!channel.channelSlug && <li>The {channelLabel}'s other playlists and shows start as not in your library, so you can add them from its page.</li>}
                                <li>
                                    A video that is also in another of the {channelLabel}'s collections goes to the one higher in
                                    the {channelLabel}'s order. Videos that are already downloaded stay where they are.
                                </li>
                            </ul>
                        )}
                </div>
            )}
        </ConfirmDialog>
    )
}

/** "Remove from channel", in the words of the Site: the collection becomes a plain one again. */
export function RemoveFromChannelDialog({open, collectionSlug, collectionTitle, channelLabel, onDismiss}: DialogProps) {
    const leave = useCollectionChannelLeave(collectionSlug, open)
    const refresh = useRefresh(collectionSlug)
    const info = leave.data
    const shared = info?.videosKeptElsewhere ?? 0

    const remove = async () => {
        try {
            await setCollectionChannel(collectionSlug, false)
            await refresh()
            toast.success(`${collectionTitle} is a plain collection now`)
            onDismiss()
        } catch (error) {
            toast.error(error instanceof Error ? error.message : `Could not remove the collection from its ${channelLabel}`)
        }
    }

    return (
        <ConfirmDialog
            open={open}
            title={info ? `Remove from ${info.channelTitle}?` : `Remove from ${channelLabel}?`}
            icon={faIcon('fass', 'link-slash')}
            iconTone="danger"
            onDismiss={onDismiss}
            confirmButton={{label: `Remove from ${channelLabel}`, onClick: remove, className: 'btn btn-danger', disabled: !info}}
        >
            {leave.error && <p className="text-danger">{leave.error.message}</p>}
            <p>
                {collectionTitle} becomes a plain collection. It keeps its episodes, profiles and files, and its genre and
                content rating.
            </p>
            {shared > 0 && (
                <p>
                    It no longer follows the {channelLabel}'s order, so {shared === 1 ? '1 video' : `${shared} videos`} that another
                    of the {channelLabel}'s collections has may be listed here too.
                </p>
            )}
        </ConfirmDialog>
    )
}
