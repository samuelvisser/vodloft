import {useEffect, useState} from 'react'
import {useQuery} from '@tanstack/react-query'
import Switch from 'react-switch'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'

import ConfirmDialog from '../../components/ConfirmDialog/ConfirmDialog'
import {names, Step, ChangeList, TitleList} from '../../components/ChangeIdentificationDialog/ChangeSteps'
import '../../components/ChangeIdentificationDialog/ChangeIdentificationDialog.css'
import {faIcon} from '../../icons/faIcon'
import {collectionWords, type Noun} from '../../lib/collectionWords'
import {previewCreatorMoves} from '../../lib/queries'
import {capitalized, joinedNames} from '../../types/creator'
import type {MoveCollection, MovedPart, SectionMove} from '../../types/schemas/creator'
import type {Names} from '../../types/schemas/source'

/** One feed or list that goes elsewhere, as the Edit page shows it. */
export type PlaceChange = {
    move: SectionMove
    title: string
    names: Names
    /** Where it is now and where it goes, in the words of its dropdown. */
    from: string
    to: string
}

type Props = {
    open: boolean
    creatorSlug: string
    changes: PlaceChange[]
    onDismiss: () => void
    /** Saves the page with the moves, and whether each collection numbers its episodes again. */
    onConfirm: (renumber: Record<string, boolean>) => Promise<void>
    error?: string | null
}

const STATE_TAGS: Record<MoveCollection['state'], string | null> = {existing: null, new: 'New', deleted: 'Deleted'}

/** Asks before the Edit page moves feeds and lists to other collections, saying for each collection what leaves and
 *  joins it, which files go, and what is numbered, renamed and rewritten again, as changing how a collection numbers
 *  its episodes does. */
export default function MoveSectionsDialog({open, creatorSlug, changes, onDismiss, onConfirm, error}: Props) {
    const [renumber, setRenumber] = useState<Record<string, boolean>>({})
    useEffect(() => {
        if (open) setRenumber({})
    }, [open])

    const moves = changes.map((change) => change.move)
    const {data: preview, isLoading, isError, error: previewError} = useQuery({
        queryKey: ['creator', creatorSlug, 'movesPreview', moves],
        enabled: open && moves.length > 0,
        gcTime: 0,
        queryFn: ({signal}) => previewCreatorMoves(creatorSlug, moves, signal),
    })

    const deletes = preview?.collections.some((collection) => collection.parts.some((part) => part.downloadsDeleted > 0)) ?? false
    const what = joinedNames(changes.map((change) => change.names)).plural

    return (
        <ConfirmDialog
            open={open}
            title={`Move the ${what}?`}
            onDismiss={onDismiss}
            icon={faIcon('fass', 'arrow-right-arrow-left')}
            iconTone={deletes ? 'danger' : 'default'}
            className="change-identification-dialog move-sections-dialog"
            confirmButton={{
                label: 'Save and move',
                onClick: () => onConfirm(renumber),
                className: deletes ? 'btn btn-danger' : 'btn btn-primary',
                disabled: !preview,
            }}
        >
            <ul className="move-sections-changes">
                {changes.map((change) => (
                    <li key={`${change.move.accountId}:${change.move.ref}`}>
                        <b>{change.title}</b>
                        <span className="change-identification-change">
                            <span className="change-identification-chip">{change.from}</span>
                            <span className="change-identification-arrow" aria-label="to">→</span>
                            <span className="change-identification-chip is-target">{change.to}</span>
                        </span>
                    </li>
                ))}
            </ul>
            {isLoading && (
                <p className="change-identification-loading" role="status">
                    <FontAwesomeIcon icon={faIcon('fass', 'spinner')} spin aria-hidden="true"/>
                    Looking at what changes…
                </p>
            )}
            {isError && (
                <p className="error" role="alert">
                    {/* A refusal says why, such as a collection that is still busy; anything else gets the general line. */}
                    {previewError instanceof Error && !(previewError instanceof TypeError) && previewError.message
                        ? previewError.message : 'VODLoft could not look up what the move does.'}
                </p>
            )}
            {preview?.collections.map((collection) => (
                <CollectionMoves
                    key={collection.slug}
                    collection={collection}
                    renumber={renumber[collection.slug] ?? true}
                    onRenumber={(again) => setRenumber((current) => ({...current, [collection.slug]: again}))}
                />
            ))}
            {error && <p className="error" role="alert">{error}</p>}
        </ConfirmDialog>
    )
}

/** What a move does to one collection, with its switch to number its episodes again. */
export function CollectionMoves({collection, renumber, onRenumber}: {
    collection: MoveCollection, renumber: boolean, onRenumber: (again: boolean) => void
}) {
    const words = collectionWords(collection.type)
    const {episode, season} = words
    const tag = STATE_TAGS[collection.state]
    const renumbered = renumber ? collection.changes : []
    // Kept numbers rename and rewrite nothing, unless files moved in, which go where the collection keeps them.
    const touched = renumber || collection.filesFollow
    const files = touched ? collection.profiles.reduce((sum, profile) => sum + (renumber ? profile.filesRenamed : 0), 0) : 0
    const metadata = touched ? collection.profiles.reduce((sum, profile) => sum + profile.metadataRewritten, 0) : 0
    return (
        <section className="move-sections-collection" aria-label={collection.title}>
            <h3>
                {collection.title}
                {tag && <span className={`move-sections-state is-${collection.state}`}>{tag}</span>}
            </h3>
            <ul className="change-identification-steps">
                {collection.parts.map((part, index) => <PartSteps key={index} part={part} season={season}/>)}
                {collection.newSeasons.length > 0 && (
                    <Step
                        icon={faIcon('fass', 'folder-plus')}
                        headline={`New ${collection.newSeasons.length === 1 ? season.singular : season.plural}`}
                        detail={names(collection.newSeasons)}
                        value={collection.newSeasons.length}
                    />
                )}
                {renumbered.length > 0 && (
                    <Step
                        icon={faIcon('fass', 'list-ol')}
                        headline={`${episode.Plural} get a new number`}
                        detail={`of ${words.count(collection.episodes)}`}
                        value={renumbered.length}
                    >
                        <ChangeList changes={renumbered}/>
                    </Step>
                )}
                {files > 0 && (
                    <Step
                        icon={faIcon('fass', 'file-pen')}
                        headline="Files renamed"
                        detail={`In ${names(collection.profiles.filter((profile) => profile.filesRenamed > 0).map((profile) => profile.name))}.`}
                        value={files}
                    />
                )}
                {metadata > 0 && (
                    <Step
                        icon={faIcon('fass', 'tags')}
                        headline="Metadata rewritten"
                        detail="In and next to the downloaded files, without downloading them again."
                        value={metadata}
                    />
                )}
                {collection.indexed && (
                    <Step
                        icon={faIcon('fass', 'magnifying-glass')}
                        headline="Indexed"
                        detail={`VODLoft looks up its ${episode.plural} at the site once it is made.`}
                        value="Then"
                    />
                )}
            </ul>
            {collection.renumberOffered && (
                <label className="change-identification-order">
                    <Switch
                        checked={renumber}
                        onChange={onRenumber}
                        onColor="#0ea5e9" offColor="#d1d5db" uncheckedIcon={false} checkedIcon={false}
                        height={18} width={34} handleDiameter={14}
                    />
                    <span>
                        <b>Number the {episode.plural} again</b>
                        <span className="help">
                            {renumber
                                ? `Closes the gaps the ${episode.plural} that leave would leave, and fits in the ones that join.`
                                : `The ${episode.plural} that stay keep their numbers; the ones that join get the next free number.`}
                        </span>
                    </span>
                </label>
            )}
        </section>
    )
}

function PartSteps({part, season}: {part: MovedPart, season: Noun}) {
    const what = part.count === 1 ? part.names.singular : part.names.plural
    // The verb that goes with them: one video moves, two videos move.
    const verb = (one: string, several: string) => part.count === 1 ? one : several
    // The feed or list they are of, unless that is what they are called already, such as Shorts.
    const section = part.sectionTitle.toLocaleLowerCase() === part.names.plural.toLocaleLowerCase() ? '' : `${part.sectionTitle}. `
    const examples = part.examples.length > 0 && <TitleList titles={part.examples} total={part.count}/>
    if (part.direction === 'in') {
        return (
            <Step
                icon={faIcon('fass', 'arrow-right-to-bracket')}
                headline={`${capitalized(what)} ${verb('joins', 'join')}`}
                detail={`From ${part.otherTitle && part.otherTitle !== part.sectionTitle ? `${part.sectionTitle} in ${part.otherTitle}` : part.sectionTitle}${part.filesMoved > 0
                    ? `, with ${part.filesMoved.toLocaleString()} ${part.filesMoved === 1 ? 'file, which is' : 'files, which are'} moved, not downloaded again` : ''}.`}
                value={part.count}
            >
                {examples}
            </Step>
        )
    }
    if (part.direction === 'season' || part.direction === 'loose') {
        const files = part.filesMoved > 0
            ? ` Their ${part.filesMoved.toLocaleString()} ${part.filesMoved === 1 ? 'file moves' : 'files move'} along, without downloading them again.` : ''
        return (
            <Step
                icon={faIcon('fass', part.direction === 'season' ? 'folder-plus' : 'folder-minus')}
                headline={part.direction === 'season'
                    ? `${capitalized(what)} ${verb('gets', 'get')} ${season.a} of ${verb('its', 'their')} own`
                    : `${capitalized(what)} ${verb('joins', 'join')} the other ${season.plural}`}
                detail={`${section}${part.direction === 'season' ? `${part.sectionTitle} becomes ${season.a}.` : `${part.sectionTitle} is no longer ${season.a}.`}${files}`}
                value={part.count}
            >
                {examples}
            </Step>
        )
    }
    if (part.direction === 'moved') {
        const files = part.filesMoved > 0
            ? `Their ${part.filesMoved.toLocaleString()} ${part.filesMoved === 1 ? 'file moves' : 'files move'} into its folder, without downloading them again.` : ''
        return (
            <Step
                icon={faIcon('fass', 'arrow-right-arrow-left')}
                headline={`${capitalized(what)} ${verb('moves', 'move')} to ${part.otherTitle ?? `another ${season.singular}`}`}
                detail={`${part.sectionTitle === part.otherTitle ? '' : section}${files}`}
                value={part.count}
            >
                {examples}
            </Step>
        )
    }
    if (part.direction === 'out') {
        return (
            <Step
                icon={faIcon('fass', 'arrow-right-from-bracket')}
                headline={`${capitalized(what)} ${verb('moves', 'move')} to ${part.otherTitle ?? 'another collection'}`}
                detail={`${section}${verb('Its', 'Their')} files move along, without downloading them again.`}
                value={part.count}
            >
                {examples}
            </Step>
        )
    }
    return (
        <>
            <Step
                icon={faIcon('fass', 'right-from-bracket')}
                headline={`${capitalized(what)} ${verb('leaves', 'leave')} your library`}
                detail={`${section}VODLoft stops looking for new ones.`}
                value={part.count}
            >
                {examples}
            </Step>
            {part.downloadsDeleted > 0 && (
                <Step
                    danger
                    icon={faIcon('fass', 'triangle-exclamation')}
                    headline="Downloads deleted"
                    detail={`In ${names(part.deletingProfiles)}${part.keptDeleted > 0
                        ? `, ${part.keptDeleted.toLocaleString()} of them kept by hand` : ''}.`}
                    value={part.downloadsDeleted}
                />
            )}
        </>
    )
}
