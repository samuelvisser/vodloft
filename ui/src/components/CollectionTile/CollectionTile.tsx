import {Link} from 'react-router-dom'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import {toImageUrl} from '../Episode/EpisodeCard'
import CollectionTileArt from '../CollectionTileArt/CollectionTileArt'
import SourceBadge from '../Source/SourceBadge'
import {wordsFor} from '../../lib/collectionWords'
import {useActiveOperation} from '../OperationNotifier/OperationNotifier'
import CollectionIndexingProgress from '../CollectionIndexingProgress/CollectionIndexingProgress'
import {BulkTileCheck} from '../ProfileBulkEdit/BulkEditControls'

type CollectionTileProps = {
    collection: {
        /** With it, the tile shows how far indexing is while the collection is being indexed. */
        id?: number
        slug: string
        title: string
        sourceKey: string
        episodeCount: number
        type?: string | null
        site?: {audioOnly?: boolean} | null
        years?: string | null
        thumbnailSquarePath?: string | null
        thumbnailPortraitPath?: string | null
        thumbnailLandscapePath?: string | null
        linkImagePath?: string | null
        logoImagePath?: string | null
        authorHeadshotPath?: string | null
    }
    /** The line under the title, such as the collection's author. */
    subtitle?: string | null
    /** Show the collection's Source on its artwork. */
    showSource?: boolean
    /** While bulk edit is on, the tile chooses the collection instead of opening it. */
    selection?: {chosen: boolean, onToggle: () => void}
}

/** A card's stats on one line, most important first: the parts that do not fit are left out from the end, and the
 *  tooltip has them all. */
export function TileStats({parts}: {parts: (string | null | undefined)[]}) {
    const shown = parts.filter((part): part is string => !!part)
    return (
        <span className="library-tile-meta library-tile-stats" title={shown.join(' • ')}>
            {shown.map((part) => <span key={part}>{part}</span>)}
        </span>
    )
}

/** A collection as the Library shows it: square artwork, its title, a line under it, and its episodes and years. */
export default function CollectionTile({collection, subtitle, showSource = true, selection}: CollectionTileProps) {
    // The tile is square, so square artwork comes first when a Source has it.
    const image = toImageUrl(
        collection.thumbnailSquarePath || collection.thumbnailPortraitPath || collection.thumbnailLandscapePath
        || collection.linkImagePath || collection.logoImagePath || collection.authorHeadshotPath,
    )
    const indexing = !!useActiveOperation('collection.index', 'collection', collection.id ?? null)
    const content = (
        <>
            <span className="library-tile-art">
                {image
                    ? <CollectionTileArt key={image} src={image}/>
                    : <span className="collection-art-placeholder"><FontAwesomeIcon icon={faIcon('fass', 'podcast')}/></span>}
                {showSource && <SourceBadge sourceKey={collection.sourceKey} className="library-tile-source"/>}
                {selection && <BulkTileCheck title={collection.title} chosen={selection.chosen} onToggle={selection.onToggle}/>}
            </span>
            <span className="library-tile-copy">
                <span className="library-tile-title">{collection.title}</span>
                {subtitle && <span className="library-tile-author">{subtitle}</span>}
                <span className="library-tile-status">
                    {/* A collection that is still being indexed has no episodes yet, only progress. */}
                    {!(indexing && collection.episodeCount === 0) && (
                        <TileStats parts={[wordsFor(collection).count(collection.episodeCount), collection.years]}/>
                    )}
                    {collection.id !== undefined && (
                        <CollectionIndexingProgress
                            collectionId={collection.id} collectionSlug={collection.slug}
                            pollForStart={collection.episodeCount === 0} className="library-collection-indexing"
                        />
                    )}
                </span>
            </span>
        </>
    )
    if (selection) {
        return (
            <div className={`library-tile bulk-tile${selection.chosen ? ' is-selected' : ''}`} role="listitem" onClick={selection.onToggle}>
                {content}
            </div>
        )
    }
    return <Link className="library-tile" to={`/collection/${collection.slug}`} role="listitem">{content}</Link>
}
