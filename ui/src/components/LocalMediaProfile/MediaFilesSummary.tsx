import type {ReactNode} from 'react'

import {useLibraryDefaults} from '../../lib/settings'
import type {LocalMediaProfileRead} from '../../types/schemas/local_media_profile'
import {SITE_DESCRIPTION_TEMPLATE, SITE_TITLE_TEMPLATE} from '../../types/schemas/collection_local_media_profile'
import OpaqueOutputTemplateCode from './OpaqueOutputTemplateCode'
import {isBeside, isInside, METADATA, THUMBNAIL} from './MediaFilesFields'

/** One thing a profile saves, marked when it comes from Settings. */
type Saved = {key: string, label: string, fromSettings?: boolean}

function SavedList({items}: {items: Saved[] | null}) {
    if (items === null) return <span className="media-files-summary__none">Loading…</span>
    if (items.length === 0) return <span className="media-files-summary__none">Nothing</span>
    return (
        <span className="media-files-summary__list">
            {items.map((item, index) => (
                <span key={item.key}>
                    {index === 0 ? item.label.charAt(0).toUpperCase() + item.label.slice(1) : item.label}
                    {item.fromSettings && <span className="media-files-summary__settings"> (Settings)</span>}
                    {index < items.length - 1 ? ', ' : ''}
                </span>
            ))}
        </span>
    )
}

function Row({label, children}: {label: string, children: ReactNode}) {
    return (
        <div>
            <dt>{label}</dt>
            <dd>{children}</dd>
        </div>
    )
}

/**
 * What a profile saves besides the media, as its edit form's Files and metadata sets it: rows for the profile's
 * details list. A mode that follows Settings shows what Settings saves now.
 */
export default function MediaFilesSummary({profile}: {profile: LocalMediaProfileRead}) {
    const {data: defaults} = useLibraryDefaults()
    const thumbnailFollows = profile.thumbnailMode === 'system'
    const metadataFollows = profile.metadataMode === 'system'
    const thumbnail = thumbnailFollows ? defaults?.thumbnailMode : profile.thumbnailMode
    const metadata = metadataFollows ? defaults?.metadataMode : profile.metadataMode
    const collection = profile.type === 'collection' ? profile : null

    const inside: Saved[] = [
        ...(isInside(THUMBNAIL, thumbnail) ? [{key: 'thumbnail', label: 'thumbnail', fromSettings: thumbnailFollows}] : []),
        ...(isInside(METADATA, metadata) ? [{key: 'metadata', label: 'metadata', fromSettings: metadataFollows}] : []),
    ]
    // "Kodi-safe music video NFO file", from the words the edit form uses.
    const nfoKind = collection?.episodeNfo === 'music_video' ? 'music video ' : ''
    const nfoLabel = `${profile.kodiSafeNfo ? 'Kodi-safe ' : ''}${nfoKind}NFO file`
    const beside: Saved[] = [
        ...(isBeside(THUMBNAIL, thumbnail) ? [{key: 'thumbnail', label: 'thumbnail image', fromSettings: thumbnailFollows}] : []),
        ...(isBeside(METADATA, metadata) ? [{
            key: 'nfo',
            label: nfoLabel,
            fromSettings: metadataFollows,
        }] : []),
        ...(profile.saveInfoJson ? [{key: 'info', label: "the site's info file"}] : []),
    ]
    const assetsFollow = collection?.downloadCollectionAssets == null
    const show: Saved[] = collection ? [
        ...(collection.showNfo ? [{key: 'nfo', label: 'show and season NFO files'}] : []),
        ...((assetsFollow ? defaults?.downloadCollectionAssets : collection.downloadCollectionAssets)
            ? [{key: 'assets', label: 'poster and background', fromSettings: assetsFollow}] : []),
    ] : []

    const savesMetadata = inside.some((item) => item.key === 'metadata') || beside.some((item) => item.key === 'nfo')
    const ownTitle = collection && collection.episodeTitleTemplate !== SITE_TITLE_TEMPLATE
    const ownDescription = collection && collection.episodeDescriptionTemplate !== SITE_DESCRIPTION_TEMPLATE

    return (
        <>
            <Row label="Inside the media"><SavedList items={defaults ? inside : null}/></Row>
            <Row label="Beside the media"><SavedList items={defaults ? beside : null}/></Row>
            {collection && <Row label="For the show"><SavedList items={defaults ? show : null}/></Row>}
            {collection && savesMetadata && (
                <Row label="Title and description">
                    {!ownTitle && !ownDescription ? "The site's own" : (
                        <div className="media-files-summary__templates">
                            <span className="media-files-summary__template-label">Title</span>
                            <OpaqueOutputTemplateCode source={collection.episodeTitleTemplate} label="Title in the metadata"/>
                            <span className="media-files-summary__template-label">Description</span>
                            <OpaqueOutputTemplateCode source={collection.episodeDescriptionTemplate} label="Description in the metadata"/>
                        </div>
                    )}
                </Row>
            )}
            <Row label="File dates">{profile.fileDateFromPublishDate ? 'Publish date' : 'Download date'}</Row>
        </>
    )
}
