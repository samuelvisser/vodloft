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
import type {CollectionReadView} from '../../types/schemas/collection'

type CollectionTileProps = {
    collection: CollectionReadView
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

/** A collection as the Library shows it, wherever it is shown: square artwork with its Source, its title, what it is
 *  on its Site (never its author), and its episodes and years. */
export default function CollectionTile({collection, selection}: CollectionTileProps) {
    // The tile is square, so square artwork comes first when a Source has it.
    const image = toImageUrl(
        collection.thumbnailSquarePath || collection.thumbnailPortraitPath || collection.thumbnailLandscapePath
        || collection.linkImagePath || collection.logoImagePath || collection.authorHeadshotPath,
    )
    const indexing = !!useActiveOperation('collection.index', 'collection', collection.id ?? null)
    const words = wordsFor(collection)
    const moves = collection.healthIssues?.moves ?? 0
    const content = (
        <>
            <span className="library-tile-art">
                {image
                    ? <CollectionTileArt key={image} src={image}/>
                    : <span className="collection-art-placeholder"><FontAwesomeIcon icon={faIcon('fass', 'podcast')}/></span>}
                <SourceBadge sourceKey={collection.sourceKey} className="library-tile-source"/>
                {moves > 0 && (
                    <span
                        className="library-tile-moves"
                        title={`${words.count(moves)} ${moves === 1 ? 'waits' : 'wait'} to move to another ${words.season.singular}`}
                    >
                        <FontAwesomeIcon icon={faIcon('fass', 'arrow-right-arrow-left')}/>
                        {moves}
                    </span>
                )}
                {selection && <BulkTileCheck title={collection.title} chosen={selection.chosen} onToggle={selection.onToggle}/>}
            </span>
            <span className="library-tile-copy">
                <span className="library-tile-title">{collection.title}</span>
                {collection.kindName && <span className="library-tile-author">{collection.kindName}</span>}
                <span className="library-tile-status">
                    {/* A collection that is still being indexed has no episodes yet, only progress. */}
                    {!(indexing && collection.episodeCount === 0) && (
                        <TileStats parts={[words.count(collection.episodeCount), collection.years]}/>
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
