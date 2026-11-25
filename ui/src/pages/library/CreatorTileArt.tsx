import type {ReactNode} from 'react'
import {useRingTone} from '../../lib/imageTone'

// The picture fills 56% of the tile (see .library-creator-avatar), so its ring sits just outside radius 0.28.
const AVATAR_RADIUS = 0.28
const AROUND_RING = 0.38

/**
 * A creator's banner behind their round picture. The ring around the picture is light on a dark banner and dark on
 * a light one, so the picture stays apart from its banner.
 */
export default function CreatorTileArt({banner, avatar, initials, children}: {
    banner?: string, avatar?: string, initials: string, children?: ReactNode,
}) {
    const tone = useRingTone(banner, AVATAR_RADIUS, AROUND_RING)
    const ring = tone === 'dark' ? 'light' : tone === 'light' ? 'dark' : undefined
    return (
        <span className="library-tile-art" style={banner ? {backgroundImage: `url("${banner}")`} : undefined}>
            {avatar
                ? <img className="library-creator-avatar" data-ring={ring} src={avatar} alt="" loading="lazy" decoding="async"/>
                : <span className="library-creator-avatar library-creator-avatar--empty" data-ring={ring} aria-hidden="true">{initials}</span>}
            {children}
        </span>
    )
}
