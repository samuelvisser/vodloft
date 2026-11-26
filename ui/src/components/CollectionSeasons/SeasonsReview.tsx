import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'

import {faIcon} from '../../icons/faIcon'
import {capitalized} from '../../types/creator'
import type {CollectionSeasonsRead, SeasonsReviewRead} from '../../types/schemas/collection_seasons'
import {FoldSteps, names, Step, TitleList} from '../ChangeIdentificationDialog/ChangeSteps'
import '../ChangeIdentificationDialog/ChangeIdentificationDialog.css'
import {CollectionMoves} from '../ReconcileDialog/ReconcileDialog'
import {type CauseRow, seasonsRows} from '../ReconcileDialog/MoveCauses'
import type {Words} from './seasonsSettings'

/** The second step of the Seasons dialog: what saving does, as the Move dialog shows a move, with the cards only the
 * Seasons dialog needs besides: the seasons it makes, the videos that get downloaded, the ones that leave, and the
 * downloaded files deleted with them. Nothing is saved until the user agrees to it. */
export default function SeasonsReview({view, review, failed, changes, words, listName, listing, listed, renumber, onRenumber, onBack, folded}: {
    view: CollectionSeasonsRead
    review: SeasonsReviewRead | undefined
    failed: string | null
    /** What the user changed that the review's causes do not name, such as a season they renamed. */
    changes: CauseRow[]
    words: Words
    /** What the collection's lists are called together, such as creator playlists and links. */
    listName: string
    /** The dialog still lists a list for the review. */
    listing: boolean
    /** The lists the dialog listed already, by title, while it waits for the others. */
    listed: string[]
    renumber: boolean
    onRenumber: (again: boolean) => void
    onBack: () => void
    /** On a phone, each card folds to one line. */
    folded: boolean
}) {
    const {season} = words
    if (failed) return <p className="error" role="alert">{failed}</p>
    if (!review) {
        return (
            <p className="change-identification-loading" role="status">
                <FontAwesomeIcon icon={faIcon('fass', 'spinner')} spin aria-hidden="true"/>
                Looking at what changes…
            </p>
        )
    }
    if (review.busy) {
        return (
            <div className="seasons-review-busy">
                <p className="change-identification-loading" role="status">
                    <FontAwesomeIcon icon={faIcon('fass', 'spinner')} spin aria-hidden="true"/>
                    {review.busy}
                </p>
                {listing && (
                    <p className="help">
                        VODLoft started listing it when you switched it on, and carries on from there. Nothing is saved
                        yet. Once VODLoft knows what is in it, this shows exactly what moves.
                    </p>
                )}
                {listing && listed.length > 0 && (
                    <div className="seasons-review-chips">
                        {listed.map((title) => (
                            <span key={title} className="seasons-review-chip">
                                <FontAwesomeIcon icon={faIcon('fass', 'check')} aria-hidden="true"/> {title} is listed
                            </span>
                        ))}
                    </div>
                )}
                {listing && (
                    <p className="help">
                        You can go back and change a setting: what is listed stays known until you close the dialog, so
                        nothing is listed twice.
                    </p>
                )}
            </div>
        )
    }
    const rows = [
        ...seasonsRows(view, review.causes),
        ...changes,
        ...review.deletedSeasons.map((name) => ({key: `deleted-${name}`, setting: name, before: season.singular, after: 'deleted'})),
    ]
    const moves = review.moves
    const moving = (moves?.parts.length ?? 0) > 0
    const nothing = !moving && review.leaving.count === 0 && review.extra.count === 0 && review.deletedFiles.count === 0
        && review.joining === 0 && review.newSeasons.length === 0
    const newSeasons = review.newSeasons.length > 0 && (
        <Step
            icon={faIcon('fass', 'folder-plus')} headline={`New ${season.plural}`} detail={`${names(review.newSeasons)}.`}
            value={review.newSeasons.length}
        />
    )
    const others = (
        <>
            {review.joining > 0 && (
                <Step
                    icon={faIcon('fass', 'download')} headline={`${capitalized(words.videos)} get downloaded`}
                    detail={`New ${words.videos} from the ${listName} join the collection. Its Download Profiles download them as they say, after saving.`}
                    value={review.joining}
                />
            )}
            {review.leaving.count > 0 && (
                <Step
                    icon={faIcon('fass', 'arrow-right-from-bracket')} headline={`${capitalized(words.videos)} leave the collection`}
                    detail="No setting you chose has them any more."
                    value={review.leaving.count}
                >
                    <TitleList titles={review.leaving.examples} total={review.leaving.count}/>
                </Step>
            )}
            {review.extra.count > 0 && (
                <Step
                    icon={faIcon('fass', 'clone')} headline={`Extra ${words.episode.plural} go`}
                    detail={`Each was a second ${words.episode.singular} of ${words.video === '' ? 'a video' : `a ${words.video}`} that stays in another ${season.singular}.`}
                    value={review.extra.count}
                >
                    <TitleList titles={review.extra.examples} total={review.extra.count}/>
                </Step>
            )}
            {review.deletedFiles.count > 0 && (
                <Step
                    icon={faIcon('fass', 'trash')} headline="Downloaded files will be deleted" danger
                    detail={`Of the ${words.episode.plural} that go${review.deletedFiles.profiles.length ? `, in ${names(review.deletedFiles.profiles)}` : ''}.`}
                    value={review.deletedFiles.count}
                >
                    <TitleList titles={review.deletedFiles.examples} total={review.deletedFiles.count}/>
                </Step>
            )}
        </>
    )
    return (
        <div className="change-identification-dialog seasons-review">
            <p className="help">
                Nothing has changed yet. Saving does all of this at once: what is downloaded is renamed into its new
                place, or downloaded again there when that place uses another Local Media Profile.
            </p>
            {rows.length > 0 && (
                <section className="seasons-review-changes" aria-labelledby="seasons-review-changed">
                    <h3 id="seasons-review-changed">What you changed</h3>
                    <ul className="seasons-review-chips" aria-label="What you changed">
                        {rows.map((row) => (
                            <li key={row.key} className="seasons-review-chip">
                                <b>{row.setting}</b>
                                {row.before && <span>{row.before}</span>}
                                <FontAwesomeIcon icon={faIcon('fass', 'arrow-right')} aria-label="to"/>
                                <span>{row.after}</span>
                            </li>
                        ))}
                    </ul>
                </section>
            )}
            <p className="help">
                Not what you want? Go <button type="button" className="seasons-review-back" onClick={onBack}>back</button> and change it.
            </p>
            <FoldSteps.Provider value={folded}>
                {moves && moving ? (
                    <CollectionMoves preview={moves} renumber={renumber} onRenumber={onRenumber} reason={false} leading={newSeasons} trailing={others}/>
                ) : (
                    <ul className="change-identification-steps">{newSeasons}{others}</ul>
                )}
            </FoldSteps.Provider>
            {nothing && (
                <p className="seasons-review-nothing" role="status">
                    <FontAwesomeIcon icon={faIcon('fass', 'circle-check')} aria-hidden="true"/>
                    <span>
                        <b>Nothing downloaded moves or leaves</b>
                        <span className="help">Saving only changes where new {words.videos} go.</span>
                    </span>
                </p>
            )}
        </div>
    )
}
