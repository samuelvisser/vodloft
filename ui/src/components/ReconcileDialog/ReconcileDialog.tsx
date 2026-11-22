import {useEffect, useState} from 'react'
import {useQuery, useQueryClient} from '@tanstack/react-query'
import Switch from 'react-switch'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import toast from '../../lib/toast'

import ConfirmDialog from '../ConfirmDialog/ConfirmDialog'
import '../ChangeIdentificationDialog/ChangeIdentificationDialog.css'
import {faIcon} from '../../icons/faIcon'
import {previewReconcile, reconcile} from '../../lib/queries'
import {collectionWords} from '../../lib/collectionWords'
import {capitalized} from '../../types/creator'
import {ChangeList, names, Step, TitleList} from '../ChangeIdentificationDialog/ChangeSteps'
import type {MovePreview, MovedPart, ReconcileResult} from '../../types/schemas/reconcile'

type Props = {
    open: boolean
    /** The API path of what moves: `/collections/<slug>` or `/episodes/<slug>`. */
    path: string
    /** What moves, such as "the episodes of Northwind Workshop". */
    what: string
    onDismiss: () => void
    onDone?: (result: ReconcileResult) => void | Promise<void>
}

/** Asks before the Move action of a collection or one episode puts its Moved episodes in the seasons they belong in
 *  now, saying what moves where and what is numbered, renamed and rewritten again. */
export default function ReconcileDialog({open, path, what, onDismiss, onDone}: Props) {
    const queryClient = useQueryClient()
    const [renumber, setRenumber] = useState(true)
    const [error, setError] = useState<string | null>(null)
    useEffect(() => {
        if (open) {
            setRenumber(true)
            setError(null)
        }
    }, [open])

    const {data: preview, isLoading, isError, error: previewError} = useQuery({
        queryKey: ['reconcilePreview', path],
        enabled: open,
        gcTime: 0,
        queryFn: ({signal}) => previewReconcile(path, signal),
    })

    const confirm = async () => {
        setError(null)
        try {
            const result = await reconcile(path, preview ? {[preview.slug]: renumber} : {})
            toast.success(`Moving ${what}`)
            await Promise.all([
                queryClient.invalidateQueries({queryKey: ['collection']}),
                queryClient.invalidateQueries({queryKey: ['episode']}),
                queryClient.invalidateQueries({queryKey: ['movesWaiting']}),
            ])
            await onDone?.(result)
            onDismiss()
        } catch (exc) {
            setError(exc instanceof Error ? exc.message : 'VODLoft could not move them.')
        }
    }

    return (
        <ConfirmDialog
            open={open}
            title={`Move ${what}?`}
            onDismiss={onDismiss}
            icon={faIcon('fass', 'arrow-right-arrow-left')}
            className="change-identification-dialog move-sections-dialog"
            confirmButton={{label: 'Move', onClick: confirm, className: 'btn btn-primary', disabled: !preview}}
        >
            <p className="help">
                What is downloaded waits where it is until you move it: moving renames its files into their new place, or
                downloads it again there when that place downloads it with another Local Media Profile.
            </p>
            {isLoading && (
                <p className="change-identification-loading" role="status">
                    <FontAwesomeIcon icon={faIcon('fass', 'spinner')} spin aria-hidden="true"/>
                    Looking at what changes…
                </p>
            )}
            {isError && (
                <p className="error" role="alert">
                    {previewError instanceof Error && !(previewError instanceof TypeError) && previewError.message
                        ? previewError.message : 'VODLoft could not look up what the move does.'}
                </p>
            )}
            {preview && <CollectionMoves preview={preview} renumber={renumber} onRenumber={setRenumber}/>}
            {error && <p className="error" role="alert">{error}</p>}
        </ConfirmDialog>
    )
}

/** What the Move action does to the collection, with its switch to number its episodes again. */
function CollectionMoves({preview, renumber, onRenumber}: {preview: MovePreview, renumber: boolean, onRenumber: (again: boolean) => void}) {
    const {episode, season} = collectionWords(preview.type)
    const renumbered = renumber ? preview.changes : []
    // Kept numbers rename and rewrite nothing, unless files moved, which go where the collection keeps them.
    const touched = renumber || preview.filesFollow
    const files = touched && renumber ? preview.profiles.reduce((sum, profile) => sum + profile.filesRenamed, 0) : 0
    const metadata = touched ? preview.profiles.reduce((sum, profile) => sum + profile.metadataRewritten, 0) : 0
    return (
        <section className="move-sections-collection" aria-label={preview.title}>
            <ul className="change-identification-steps">
                {preview.parts.map((part, index) => <PartStep key={index} part={part} season={season.singular}/>)}
                {renumbered.length > 0 && (
                    <Step icon={faIcon('fass', 'list-ol')} headline={`${episode.Plural} get a new number`} detail={null} value={renumbered.length}>
                        <ChangeList changes={renumbered}/>
                    </Step>
                )}
                {files > 0 && (
                    <Step
                        icon={faIcon('fass', 'file-pen')}
                        headline="Files renamed"
                        detail={`In ${names(preview.profiles.filter((profile) => profile.filesRenamed > 0).map((profile) => profile.name))}.`}
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
            </ul>
            {preview.renumberOffered && (
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
                                ? `Numbers each ${season.singular} again, with the ${episode.plural} that moved in it.`
                                : `The ${episode.plural} keep their numbers.`}
                        </span>
                    </span>
                </label>
            )}
        </section>
    )
}

/** The videos of one list that move to another season. */
function PartStep({part, season}: {part: MovedPart, season: string}) {
    const what = part.count === 1 ? part.names.singular : part.names.plural
    const files = part.filesMoved > 0
        ? ` ${part.filesMoved === 1 ? 'Its file moves' : `Their ${part.filesMoved.toLocaleString()} files move`} into its folder, without downloading ${part.filesMoved === 1 ? 'it' : 'them'} again.` : ''
    // The list they are of, unless that is what they are called already.
    const label = part.label.toLocaleLowerCase() === part.names.plural.toLocaleLowerCase() ? '' : `${part.label}.`
    return (
        <Step
            icon={faIcon('fass', 'arrow-right-arrow-left')}
            headline={`${capitalized(what)} ${part.count === 1 ? 'moves' : 'move'} to the ${season} ${part.toSeason}`}
            detail={`${label}${files}`.trim() || undefined}
            value={part.count}
        >
            {part.examples.length > 0 && <TitleList titles={part.examples} total={part.count}/>}
        </Step>
    )
}
