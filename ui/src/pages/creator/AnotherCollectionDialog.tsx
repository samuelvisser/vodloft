import {useState} from 'react'
import ConfirmDialog from '../../components/ConfirmDialog/ConfirmDialog'
import {faIcon} from '../../icons/faIcon'
import {collectionWords} from '../../lib/collectionWords'
import {capitalized} from '../../types/creator'
import type {CreatorPageRead} from '../../types/schemas/creator'
import type {AccountSection, Place} from './CreatorSectionsEditor'

/** The creator's collections, other than their own and the one it is in now, that a feed or list can go into. */
export function otherCollections(creator: CreatorPageRead, {account, section}: AccountSection) {
    // The main feed, such as YouTube's Videos, lists everything the creator's own collection has, so it stays there.
    if (section.kind === 'feed' && section.role === 'main') return []
    return account.gatherableSlugs
        .filter((slug) => slug !== account.mainCollectionSlug && slug !== section.collectionSlug)
        .flatMap((slug) => creator.collections.filter((collection) => collection.slug === slug))
}

/** Asks which of the creator's other collections a feed or list goes into, and for a list whether it becomes a
 * season of it. */
export default function AnotherCollectionDialog({creator, item, confirmLabel, onPick, onDismiss}: {
    creator: CreatorPageRead
    item: AccountSection
    confirmLabel: string
    onPick: (place: Place) => void | Promise<void>
    onDismiss: () => void
}) {
    const {account, section} = item
    const collections = otherCollections(creator, item)
    const [slug, setSlug] = useState(collections[0]?.slug ?? '')
    const [asSeason, setAsSeason] = useState(true)
    const chosen = collections.find((collection) => collection.slug === slug)
    const season = collectionWords(chosen?.type).season
    const list = section.kind === 'list' && account.site.linkSeasons
    const media = section.kind === 'feed' ? section.names.plural : account.site.mediaNames.plural
    return (
        <ConfirmDialog
            open
            title={`Another collection for ${section.title}`}
            icon={faIcon('fass', 'folder-plus')}
            onDismiss={onDismiss}
            confirmButton={{
                label: confirmLabel, disabled: !chosen,
                onClick: () => onPick(`${list && !asSeason ? 'main_loose' : 'main'}@${slug}`),
            }}
        >
            <p>Its {media} go into the collection you pick. That collection keeps what it has.</p>
            <fieldset className="creator-presets">
                <legend>Collection</legend>
                {collections.map((collection) => (
                    <label key={collection.slug} className={`creator-preset${slug === collection.slug ? ' is-on' : ''}`}>
                        <input type="radio" name="another-collection" checked={slug === collection.slug} onChange={() => setSlug(collection.slug)}/>
                        <b>{collection.title}</b>
                        <span>{collectionWords(collection.type).count(collection.episodeCount)}</span>
                    </label>
                ))}
            </fieldset>
            {list && chosen && (
                <fieldset className="creator-presets">
                    <legend>{capitalized(section.names.singular)}</legend>
                    <label className={`creator-preset${asSeason ? ' is-on' : ''}`}>
                        <input type="radio" name="another-collection-season" checked={asSeason} onChange={() => setAsSeason(true)}/>
                        <b>As {season.a}</b>
                        <span>{capitalized(season.a)} of {chosen.title}</span>
                    </label>
                    <label className={`creator-preset${!asSeason ? ' is-on' : ''}`}>
                        <input type="radio" name="another-collection-season" checked={!asSeason} onChange={() => setAsSeason(false)}/>
                        <b>Not as {season.a}</b>
                        <span>Its {media} join the others in {chosen.title}</span>
                    </label>
                </fieldset>
            )}
        </ConfirmDialog>
    )
}
