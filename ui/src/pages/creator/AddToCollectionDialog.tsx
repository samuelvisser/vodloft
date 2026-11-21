import {useState} from 'react'
import ConfirmDialog from '../../components/ConfirmDialog/ConfirmDialog'
import {faIcon} from '../../icons/faIcon'
import {collectionWords} from '../../lib/collectionWords'
import {capitalized} from '../../types/creator'
import type {CreatorPageRead} from '../../types/schemas/creator'
import {mainSeasonOf, mainTitleOf, placeMove, type AccountSection, type Place} from './CreatorSectionsEditor'

/** A collection of the creator that a feed or list can go into: their main collection first, which VODLoft makes
 * when it isn't there yet (``slug`` null), then the other ones that hold several feeds and lists. */
export type CollectionChoice = {slug: string | null, main: boolean, title: string, type?: string, episodeCount?: number}

/** Whether a list goes into a collection as a season of it, or with its videos among the others there. */
function seasoned({account, section}: AccountSection) {
    return section.kind === 'list' && account.site.linkSeasons
}

/** The collections of the creator that a feed or list can go into, their main collection first. A list only goes into
 * one where lists can be seasons; the main feed, such as YouTube's Videos, has the main collection's link, so it only
 * goes there. */
export function collectionChoices(creator: CreatorPageRead, item: AccountSection): CollectionChoice[] {
    const {account, section} = item
    if (section.kind !== 'feed' && !seasoned(item)) return []
    const main = creator.collections.find((collection) => collection.slug === account.mainCollectionSlug)
    const choices: CollectionChoice[] = [{
        slug: main?.slug ?? null, main: true, title: mainTitleOf(creator, account), type: main?.type, episodeCount: main?.episodeCount,
    }]
    if (section.kind === 'feed' && section.role === 'main') return choices
    return [...choices, ...account.gatherableSlugs
        .filter((slug) => slug !== account.mainCollectionSlug)
        .flatMap((slug) => creator.collections.filter((collection) => collection.slug === slug))
        .map((collection) => ({slug: collection.slug, main: false, title: collection.title, type: collection.type, episodeCount: collection.episodeCount}))]
}

/** Whether the dialog has a choice to offer for a feed or list in ``place``: another collection, or for a list, being
 * a season or not. */
export function hasCollectionChoice(creator: CreatorPageRead, item: AccountSection, place?: Place) {
    const choices = collectionChoices(creator, item)
    if (seasoned(item)) return choices.length > 0
    const at = place ? placeMove(place).collectionSlug ?? item.account.mainCollectionSlug : undefined
    return choices.some((choice) => choice.slug !== at)
}

/** Asks which of the creator's collections a feed or list goes into, their main collection to start with, and for a
 * list whether it becomes a season of it or adds its contents only. */
export default function AddToCollectionDialog({creator, item, place, confirmLabel, title, several = false, onPick, onDismiss}: {
    creator: CreatorPageRead
    /** The feed or list, or the first of several that go to the same place. */
    item: AccountSection
    /** Where it goes now, which the dialog starts with. */
    place?: Place
    confirmLabel: string
    /** The dialog's title, when it is about several. */
    title?: string
    /** Whether several feeds or lists go there together. */
    several?: boolean
    onPick: (place: Place) => void | Promise<void>
    onDismiss: () => void
}) {
    const {account, section} = item
    const collections = collectionChoices(creator, item)
    const start = place ? placeMove(place) : null
    const startKey = start?.collectionSlug ?? ''
    const [key, setKey] = useState(collections.some((collection) => !collection.main && collection.slug === startKey) ? startKey : '')
    const [asSeason, setAsSeason] = useState(start?.target !== 'main_loose')
    const keyOf = (collection: CollectionChoice) => collection.main ? '' : collection.slug ?? ''
    const chosen = collections.find((collection) => keyOf(collection) === key)
    const season = chosen?.main ? mainSeasonOf(creator, account) : collectionWords(chosen?.type).season
    const list = seasoned(item)
    const media = section.kind === 'feed' ? section.names.plural : account.site.mediaNames.plural
    return (
        <ConfirmDialog
            open
            title={title ?? `Add ${section.title} to a collection`}
            icon={faIcon('fass', 'folder-plus')}
            onDismiss={onDismiss}
            confirmButton={{
                label: confirmLabel, disabled: !chosen,
                onClick: () => onPick(`${list && !asSeason ? 'main_loose' : 'main'}${key ? `@${key}` : ''}`),
            }}
        >
            <p>{several ? 'Their' : 'Its'} {media} go into the collection you pick. That collection keeps what it has.</p>
            <fieldset className="creator-presets">
                <legend>Collection</legend>
                {collections.map((collection) => (
                    <label key={keyOf(collection)} className={`creator-preset${key === keyOf(collection) ? ' is-on' : ''}`}>
                        <input type="radio" name="add-to-collection" checked={key === keyOf(collection)} onChange={() => setKey(keyOf(collection))}/>
                        <b>{collection.title}</b>
                        <span>
                            {collection.main ? 'Main collection' : 'Collection'}
                            {' · '}
                            {collection.slug ? collectionWords(collection.type).count(collection.episodeCount ?? 0) : 'Made when you add this'}
                        </span>
                    </label>
                ))}
            </fieldset>
            {list && chosen && (
                <fieldset className="creator-presets">
                    <legend>{capitalized(section.names.singular)}</legend>
                    <label className={`creator-preset${asSeason ? ' is-on' : ''}`}>
                        <input type="radio" name="add-to-collection-season" checked={asSeason} onChange={() => setAsSeason(true)}/>
                        <b>As {season.a}</b>
                        <span>{capitalized(season.a)} of {chosen.title}</span>
                    </label>
                    <label className={`creator-preset${!asSeason ? ' is-on' : ''}`}>
                        <input type="radio" name="add-to-collection-season" checked={!asSeason} onChange={() => setAsSeason(false)}/>
                        <b>Add its contents only</b>
                        <span>Its {media} join the others in {chosen.title}, without {season.a} of their own</span>
                    </label>
                </fieldset>
            )}
        </ConfirmDialog>
    )
}
