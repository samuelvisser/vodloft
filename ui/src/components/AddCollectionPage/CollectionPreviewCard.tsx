type Props = {
    title: string
    authorName?: string | null
    description?: string | null
    imageUrl?: string | null
    backgroundUrl?: string | null
}

/** A collection that is being added, from what VODLoft already knows about it. */
export default function CollectionPreviewCard({title, authorName, description, imageUrl, backgroundUrl}: Props) {
    const background = backgroundUrl || imageUrl
    return (
        <div className="dw-card" role="region" aria-label="Collection preview">
            {background ? <div className="dw-card-bg" style={{backgroundImage: `url(${background})`}}/> : null}
            <div className="dw-card-media">
                {imageUrl ? (
                    <img className="dw-card-img" src={imageUrl} alt=""/>
                ) : (
                    <div className="dw-card-img dw-card-img-placeholder" aria-hidden="true"/>
                )}
            </div>
            <div className="dw-card-body">
                <div className="dw-card-title">{title}</div>
                {authorName ? <div className="dw-card-author">{authorName}</div> : null}
                {description && <div className="dw-card-desc line-clamp-6">{description}</div>}
            </div>
        </div>
    )
}

/** The aside of a later wizard step: the show chosen in the first step. */
export function ChosenCollectionCard({collection}: {collection?: {
    title: string
    authorName?: string | null
    description?: string | null
    thumbnailPortraitPath?: string | null
    thumbnailLandscapePath?: string | null
    backgroundImagePath?: string | null
}}) {
    if (!collection) return null
    return (
        <CollectionPreviewCard
            title={collection.title}
            authorName={collection.authorName}
            description={collection.description}
            imageUrl={collection.thumbnailPortraitPath || collection.thumbnailLandscapePath}
            backgroundUrl={collection.backgroundImagePath}
        />
    )
}
