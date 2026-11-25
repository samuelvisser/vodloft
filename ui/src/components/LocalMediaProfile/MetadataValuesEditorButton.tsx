import {useId, useMemo, useState} from 'react'
import {createPortal} from 'react-dom'

import CustomMetadataEditor from '../CustomMetadataEditor/CustomMetadataEditor'
import SimpleSelect from '../common/SimpleSelect'
import {useCollections} from '../../lib/queries'
import {profileScopesFor} from '../../lib/collectionWords'
import type {CollectionLocalMediaProfileScope} from '../../types/local_media_profile'
import {createSelectRegistry} from '../../utils/selectRegistry'


/** Opens a collection's metadata, by default from the template reference's Metadata tab. The dialog starts with a
 * pick of the collections the profile can be used for, and then shows what the collection's own Metadata dialog
 * shows. */
export default function MetadataValuesEditorButton({
    collectionScope, siteKeys, addFields, className = 'template-reference__button', label = 'Define values',
}: {
    collectionScope: CollectionLocalMediaProfileScope
    /** The Sites the profile is for; undefined for every Site. */
    siteKeys?: string[]
    /** Fields to start with as new rows, such as the ones the template uses that do not exist yet. */
    addFields?: readonly string[]
    className?: string
    label?: string
}) {
    const [open, setOpen] = useState(false)
    const [slug, setSlug] = useState<string | null>(null)
    const pickerId = `metadata-values-collection-${useId()}`
    const collectionsQuery = useCollections()
    const collections = useMemo(
        () => (collectionsQuery.data ?? [])
            .filter((collection) => profileScopesFor(String(collection.type)).includes(collectionScope))
            // A collection whose Site is not known yet counts as on every Site, as it does for the profile.
            .filter((collection) => !siteKeys || !collection.site || siteKeys.includes(collection.site.key))
            .sort((left, right) => left.title.localeCompare(right.title)),
        [collectionScope, collectionsQuery.data, siteKeys],
    )
    const registry = useMemo(() => createSelectRegistry(
        'MetadataValuesCollections',
        Object.fromEntries(collections.map((collection) => [collection.slug, {label: collection.title}])),
        collections.map((collection) => collection.slug),
    ), [collections])
    const collection = collections.find((candidate) => candidate.slug === slug)

    const picker = (
        <div className="custom-metadata-field">
            <label htmlFor={pickerId}>Collection</label>
            <SimpleSelect
                inputId={pickerId}
                registry={registry}
                value={collection?.slug ?? null}
                onChange={setSlug}
                placeholder={collectionsQuery.isLoading ? 'Loading collections…' : 'Choose a collection'}
                isDisabled={collectionsQuery.isLoading}
            />
            {!collectionsQuery.isLoading && collections.length === 0 && (
                <p className="custom-metadata-empty">No collections in your Library can use this profile yet.</p>
            )}
        </div>
    )

    return (
        <>
            <button
                type="button"
                className={className}
                onClick={() => {
                    setSlug(null)
                    setOpen(true)
                }}
            >
                {label}
            </button>
            {open ? createPortal(
                <CustomMetadataEditor
                    open
                    title="Metadata values"
                    scope="collection"
                    picker={picker}
                    addFields={addFields}
                    metadata={collection?.customMetadata}
                    endpoint={collection ? `/collections/${encodeURIComponent(collection.slug)}/metadata` : undefined}
                    invalidateQueryKeys={collection ? [
                        ['collection', collection.slug],
                        ['collections'],
                        ['collectionsView'],
                    ] : []}
                    onDismiss={() => setOpen(false)}
                />,
                document.body,
            ) : null}
        </>
    )
}
