import {useState} from 'react'
import ConfirmDialog from '../../components/ConfirmDialog/ConfirmDialog'
import {faIcon} from '../../icons/faIcon'
import type {Noun} from '../../lib/collectionWords'
import {capitalized} from '../../types/creator'
import type {CreatorSectionRead, SectionPlan} from '../../types/schemas/creator'

/** On the Add creator page: asks which new collection of another feed or list a feed or list goes into, and for a
 * list whether it becomes a season of it or adds its contents only, as the Edit page's Add to collection does. */
export default function AddToNewCollectionDialog({section, collections, plan, seasons, season, media, onPick, onDismiss}: {
    section: CreatorSectionRead
    /** The feeds and lists set to become a collection of their own, with the titles those collections get. */
    collections: {ref: string, title: string}[]
    /** Where it goes now, which the dialog starts with. */
    plan?: SectionPlan
    /** It is a list that can be a season of the collection. */
    seasons: boolean
    season: Noun
    /** What it holds, such as tracks. */
    media: string
    onPick: (intoRef: string, asSeason: boolean) => void
    onDismiss: () => void
}) {
    const [ref, setRef] = useState(collections.some((collection) => collection.ref === plan?.intoRef) ? plan!.intoRef! : collections[0]?.ref ?? '')
    const [asSeason, setAsSeason] = useState(plan?.target !== 'main_loose')
    const chosen = collections.find((collection) => collection.ref === ref)
    return (
        <ConfirmDialog
            open
            title={`Add ${section.title} to a collection`}
            icon={faIcon('fass', 'folder-plus')}
            onDismiss={onDismiss}
            confirmButton={{label: 'Add', disabled: !chosen, onClick: () => onPick(ref, seasons && asSeason)}}
        >
            <p>Its {media} go into the new collection you pick, which is made when you add this.</p>
            <fieldset className="creator-presets">
                <legend>Collection</legend>
                {collections.map((collection) => (
                    <label key={collection.ref} className={`creator-preset${ref === collection.ref ? ' is-on' : ''}`}>
                        <input type="radio" name="add-to-new-collection" checked={ref === collection.ref} onChange={() => setRef(collection.ref)}/>
                        <b>{collection.title}</b>
                        <span>Collection · Made when you add this</span>
                    </label>
                ))}
            </fieldset>
            {seasons && chosen && (
                <fieldset className="creator-presets">
                    <legend>{capitalized(section.names.singular)}</legend>
                    <label className={`creator-preset${asSeason ? ' is-on' : ''}`}>
                        <input type="radio" name="add-to-new-collection-season" checked={asSeason} onChange={() => setAsSeason(true)}/>
                        <b>As {season.a}</b>
                        <span>{capitalized(season.a)} of {chosen.title}</span>
                    </label>
                    <label className={`creator-preset${!asSeason ? ' is-on' : ''}`}>
                        <input type="radio" name="add-to-new-collection-season" checked={!asSeason} onChange={() => setAsSeason(false)}/>
                        <b>Add its contents only</b>
                        <span>Its {media} join the others in {chosen.title}, without {season.a} of their own</span>
                    </label>
                </fieldset>
            )}
        </ConfirmDialog>
    )
}
