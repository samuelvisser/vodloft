type Props = {
    title: string
    authorName?: string | null
    description?: string | null
    imageUrl?: string | null
    backgroundUrl?: string | null
}

/** A show that is being added, from what VODLoft already knows about it. */
export default function ShowPreviewCard({title, authorName, description, imageUrl, backgroundUrl}: Props) {
    const background = backgroundUrl || imageUrl
    return (
        <div className="dw-card" role="region" aria-label="Show preview">
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
export function ChosenShowCard({show}: {show?: {
    title: string
    authorName?: string | null
    description?: string | null
    thumbnailPortraitPath?: string | null
    thumbnailLandscapePath?: string | null
    backgroundImagePath?: string | null
}}) {
    if (!show) return null
    return (
        <ShowPreviewCard
            title={show.title}
            authorName={show.authorName}
            description={show.description}
            imageUrl={show.thumbnailPortraitPath || show.thumbnailLandscapePath}
            backgroundUrl={show.backgroundImagePath}
        />
    )
}
