import {useState} from 'react'
import {useQuery, useQueryClient} from '@tanstack/react-query'
import {z} from 'zod'
import ConfirmDialog from '../ConfirmDialog/ConfirmDialog'
import StreamAddressField from '../StreamProfile/StreamAddressField'
import {apiJson, publicAddress} from '../../lib/api'
import {faIcon} from '../../icons/faIcon'
import './Account.css'

const StreamAccessSchema = z.object({playlistPath: z.string(), guidePath: z.string(), episodesPath: z.string()})
const QUERY_KEY = ['streamAccess']

/** The playlist and guide with all of the user's IPTV channels, for TV apps that list them together. */
export default function StreamAccessCard() {
    const qc = useQueryClient()
    const {data} = useQuery({
        queryKey: QUERY_KEY,
        queryFn: () => apiJson('/stream-profiles/stream-access', StreamAccessSchema.parse),
    })
    const [confirmOpen, setConfirmOpen] = useState(false)
    const [regenerating, setRegenerating] = useState(false)

    const regenerate = async () => {
        setConfirmOpen(false)
        setRegenerating(true)
        try {
            const updated = await apiJson('/stream-profiles/stream-access/regenerate', StreamAccessSchema.parse, {method: 'POST'})
            qc.setQueryData(QUERY_KEY, updated)
        } finally {
            setRegenerating(false)
        }
    }

    return (
        <div className="account-card account-card-wide">
            <h2>Watch in other apps</h2>
            <p>
                Add this playlist to a TV app, such as TiviMate or Kodi&apos;s IPTV Simple, to watch all your IPTV
                channels with their guide. Create a channel with an IPTV Stream Profile.
            </p>
            <div className="form">
                <StreamAddressField
                    id="account-playlist-url"
                    label="Playlist URL"
                    what="playlist URL"
                    value={data ? publicAddress(data.playlistPath) : undefined}
                    onRegenerate={() => setConfirmOpen(true)}
                    regenerating={regenerating}
                    help="Keep it to yourself: anyone with this address can watch your channels."
                />
                <StreamAddressField
                    id="account-guide-url"
                    label="Guide URL"
                    what="guide URL"
                    value={data ? publicAddress(data.guidePath) : undefined}
                    help="Most apps find the guide in the playlist; add it yourself where an app asks for an EPG address."
                />
                <StreamAddressField
                    id="account-episodes-url"
                    label="Episode playlist URL"
                    what="episode playlist URL"
                    value={data ? publicAddress(data.episodesPath) : undefined}
                    help={(
                        <>
                            Every episode of the channels that have <strong>Also list episodes on their own</strong> on,
                            for apps without a guide, such as VLC.
                        </>
                    )}
                />
            </div>
            <ConfirmDialog
                open={confirmOpen}
                title="Regenerate your playlist address"
                onDismiss={() => setConfirmOpen(false)}
                icon={faIcon('fass', 'rotate')}
                iconTone="danger"
                confirmButton={{
                    label: 'Regenerate addresses',
                    onClick: regenerate,
                    icon: faIcon('fass', 'rotate'),
                    className: 'btn btn-danger',
                }}
            >
                <p>Your current playlist, guide and episode playlist addresses stop working at once.</p>
                <p>TV apps that use them will need the new ones.</p>
            </ConfirmDialog>
        </div>
    )
}
