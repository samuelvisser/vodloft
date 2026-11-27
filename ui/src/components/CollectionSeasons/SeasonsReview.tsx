import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'

import {faIcon} from '../../icons/faIcon'
import {capitalized} from '../../types/creator'
import type {CollectionSeasonsRead, SeasonsReviewRead} from '../../types/schemas/collection_seasons'
import {FoldSteps, names, Step, TitleList} from '../ChangeIdentificationDialog/ChangeSteps'
import '../ChangeIdentificationDialog/ChangeIdentificationDialog.css'
import {CollectionMoves} from '../ReconcileDialog/ReconcileDialog'
import {type CauseRow, seasonsRows} from '../ReconcileDialog/MoveCauses'
import type {Words} from './seasonsSettings'
import ProgressSteps from '../common/ProgressSteps'
import type {ProgressStep} from '../../types/progress'
import {useOperations} from '../OperationNotifier/OperationNotifier'
import {presentOperationProgress} from '../../lib/operationProgress'
import {frontendOperationDefinitions} from '../../lib/operationDefinitions'

/** The second step of the Seasons dialog: what saving does, as the Move dialog shows a move, with the cards only the
 * Seasons dialog needs besides: the seasons it makes, the videos that get downloaded, the ones that leave, and the
 * downloaded files deleted with them. Nothing is saved until the user agrees to it. */
export default function SeasonsReview({view, review, failed, changes, words, listName, listing, listings = [], renumber, onRenumber, onBack, folded, alone = true}: {
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
    /** What the dialog lists for the review, a step each, while it waits for them. */
    listings?: ProgressStep[]
    renumber: boolean
    onRenumber: (again: boolean) => void
    onBack: () => void
    /** On a phone, each card folds to one line. */
    folded: boolean
    /** The review of one collection on its own; among the reviews of several, what they share is said once above them. */
    alone?: boolean
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
    if (review.busy && listing && listings.length > 0) {
        const done = listings.filter((step) => step.state !== 'running').length
        // The ones still listing first, then the ones that could not be listed, then the ones done.
        const order = {running: 0, failed: 1} as Record<string, number>
        const steps = [...listings].sort((a, b) => (order[a.state] ?? 2) - (order[b.state] ?? 2))
        return (
            <div className="seasons-review-busy">
                <p className="change-identification-loading" role="status">
                    <FontAwesomeIcon icon={faIcon('fass', 'spinner')} spin aria-hidden="true"/>
                    <span>Listing what you switched on: <b>{done.toLocaleString()} of {listings.length.toLocaleString()}</b> done</span>
                </p>
                <ProgressSteps steps={steps} className="is-plain seasons-review-listings" label="Listings"/>
                <p className="help">
                    Once VODLoft knows what is in each of them, this shows exactly what moves. Nothing is saved yet, and
                    going back keeps what is listed.
                </p>
            </div>
        )
    }
    if (review.busy && review.busyOperation) return <WaitingFor operationId={review.busyOperation} text={review.busy}/>
    if (review.busy) {
        return (
            <p className="change-identification-loading" role="status">
                <FontAwesomeIcon icon={faIcon('fass', 'spinner')} spin aria-hidden="true"/>
                {review.busy}
            </p>
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
    const alreadyWaiting = review.alreadyWaiting.count > 0 && (
        <Step
            icon={faIcon('fass', 'clock')} headline="Already waiting to move"
            detail="Of the downloads that move, these already waited to move before your changes, such as after a creator moved them to another list. They move along when you save."
            value={review.alreadyWaiting.count}
        >
            <TitleList titles={review.alreadyWaiting.examples} total={review.alreadyWaiting.count}/>
        </Step>
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
            {alone && <SavingDoes/>}
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
            {alone && <GoBack onBack={onBack}/>}
            <FoldSteps.Provider value={folded}>
                {moves && moving ? (
                    <CollectionMoves preview={moves} renumber={renumber} onRenumber={onRenumber} reason={false} leading={<>{newSeasons}{alreadyWaiting}</>} trailing={others}/>
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

/** What saving does, said once above a review. */
export function SavingDoes() {
    return (
        <p className="help">
            Nothing has changed yet. Saving does all of this at once: what is downloaded is renamed into its new
            place, or downloaded again there when that place uses another Local Media Profile.
        </p>
    )
}

export function GoBack({onBack}: {onBack: () => void}) {
    return (
        <p className="help">
            Not what you want? Go <button type="button" className="seasons-review-back" onClick={onBack}>back</button> and change it.
        </p>
    )
}

/** What a save of seasons settings does now, step by step, while the user waits for it. */
/** The task the review waits for, with the steps of its plan as it goes, and why the review waits for it. */
function WaitingFor({operationId, text}: {operationId: string, text: string}) {
    const {operations} = useOperations()
    const operation = operations.find((candidate) => candidate.id === operationId)
    const progress = presentOperationProgress(operation)
    const steps = progress?.steps ?? []
    const definition = operation && (frontendOperationDefinitions as Record<string, {label: string} | undefined>)[operation.kind]
    return (
        <div className="seasons-review-busy">
            <section className="seasons-saving" aria-live="polite">
                <p className="change-identification-loading" role="status">
                    <FontAwesomeIcon icon={faIcon('fass', 'spinner')} spin aria-hidden="true"/>
                    <b>{definition?.label ?? 'Working on it'}</b>
                </p>
                {steps.length > 0
                    ? <ProgressSteps steps={steps} className="is-plain" label="What VODLoft is doing"/>
                    : progress?.detail && <p className="help">{progress.detail}</p>}
            </section>
            <p className="help">{text}</p>
        </div>
    )
}

export function SavingProgress({steps}: {steps: ProgressStep[]}) {
    const now = steps.find((step) => step.state === 'running')
    return (
        <section className="seasons-saving" aria-live="polite">
            <p className="change-identification-loading" role="status">
                <FontAwesomeIcon icon={faIcon('fass', 'spinner')} spin aria-hidden="true"/>
                <b>{now ? now.label : 'Saving'}…</b>
            </p>
            {steps.length > 0 && <ProgressSteps steps={steps} className="is-plain" label="What saving does"/>}
        </section>
    )
}
