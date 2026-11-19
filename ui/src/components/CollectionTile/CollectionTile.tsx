import type {ReactNode} from 'react'
import {Link} from 'react-router-dom'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import {toImageUrl} from '../Episode/EpisodeCard'
import CollectionTileArt from '../CollectionTileArt/CollectionTileArt'
import SourceBadge from '../Source/SourceBadge'

type CollectionTileProps = {
    collection: {
        slug: string
        title: string
        sourceKey: string
        episodeCount: number
        years?: string | null
        thumbnailSquarePath?: string | null
        thumbnailPortraitPath?: string | null
        thumbnailLandscapePath?: string | null
        logoImagePath?: string | null
        authorHeadshotPath?: string | null
    }
    /** The line under the title, such as the collection's author. */
    subtitle?: string | null
    /** Show the collection's Source on its artwork. */
    showSource?: boolean
    /** More beside the episode count, such as how far indexing is. */
    children?: ReactNode
}

/** A collection as the Library shows it: square artwork, its title, a line under it, and its episodes and years. */
export default function CollectionTile({collection, subtitle, showSource = true, children}: CollectionTileProps) {
    // The tile is square, so square artwork comes first when a Source has it.
    const image = toImageUrl(
        collection.thumbnailSquarePath || collection.thumbnailPortraitPath || collection.thumbnailLandscapePath
        || collection.logoImagePath || collection.authorHeadshotPath,
    )
    return (
        <Link className="library-tile" to={`/collection/${collection.slug}`} role="listitem">
            <span className="library-tile-art">
                {image
                    ? <CollectionTileArt key={image} src={image}/>
                    : <span className="collection-art-placeholder"><FontAwesomeIcon icon={faIcon('fass', 'podcast')}/></span>}
                {showSource && <SourceBadge sourceKey={collection.sourceKey} className="library-tile-source"/>}
            </span>
            <span className="library-tile-copy">
                <span className="library-tile-title">{collection.title}</span>
                {subtitle && <span className="library-tile-author">{subtitle}</span>}
                <span className="library-tile-status">
                    <span className="library-tile-meta">
                        <span>{collection.episodeCount} episodes</span>
                        {collection.years && <span>{collection.years}</span>}
                    </span>
                    {children}
                </span>
            </span>
        </Link>
    )
}
