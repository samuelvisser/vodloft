import {useCallback, useEffect, useState, type ReactNode} from 'react'
import type {IconProp} from '@fortawesome/fontawesome-svg-core'
import {useQuery} from '@tanstack/react-query'
import Switch from 'react-switch'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {toast} from 'react-hot-toast'

import ConfirmDialog from '../ConfirmDialog/ConfirmDialog'
import {faIcon} from '../../icons/faIcon'
import {apiUrl} from '../../lib/api'
import {OperationStartError, useStartOperation} from '../../lib/operations'
import {EpisodeIdentifierReg, EpisodeOrderReg, type EpisodeIdentifierValue, type EpisodeOrderValue} from '../../types/collection'
import {useLoadMoreOnScroll} from '../../lib/useLoadMoreOnScroll'
import './ChangeIdentificationDialog.css'

type IdentificationChange = {title: string; before: string; after: string}

type Preview = {
    episodeIdentifier: EpisodeIdentifierValue
    episodes: number
    episodesRenumbered: number
    /** Every episode that gets a new number, newest first. */
    changes: IdentificationChange[]
    becomeAuxiliary: number
    profiles: {name: string; filesRenamed: number; metadataRewritten: number}[]
    downloadProfiles: {name: string; removed: number; noLongerWanted: number; newlyWanted: number}[]
    busy: string | null
}

type Props = {
    open: boolean
    collectionSlug: string
    collectionTitle: string
    /** The identification the collection has now, and the one picked. */
    current: EpisodeIdentifierValue
    target: EpisodeIdentifierValue | null
    episodeOrder: EpisodeOrderValue
    onDismiss: () => void
    /** The change started: its operation shows on the collection page. */
    onStarted: () => void
}

// Shown before the list is opened up.
const EXAMPLES = 3
// Rows added each time the end of the opened list scrolls into view.
const PAGE = 50

/** A few renumbered episodes, which open up into a list of all of them that renders more as it scrolls. */
function ChangeList({changes}: {changes: IdentificationChange[]}) {
    const [shown, setShown] = useState(EXAMPLES)
    const all = shown > EXAMPLES
    const more = useCallback(() => setShown((current) => Math.min(changes.length, current + PAGE)), [changes.length])
    const {rootRef, endRef} = useLoadMoreOnScroll<HTMLUListElement, HTMLLIElement>(all && shown < changes.length, more)
    return (
        <>
            <ul ref={rootRef} className={`change-identification-examples${all ? ' is-all' : ''}`}>
                {changes.slice(0, shown).map((change, index) => (
                    <li key={index}>
                        <span className="change-identification-before">{change.before}</span>
                        <span className="change-identification-arrow" aria-label="becomes">→</span>
                        <b className="change-identification-after">{change.after}</b>
                        <span className="change-identification-title">{change.title}</span>
                    </li>
                ))}
                {all && shown < changes.length && (
                    <li ref={endRef} className="change-identification-end" role="status">
                        <FontAwesomeIcon icon={faIcon('fass', 'spinner')} spin aria-hidden="true"/>
                        Loading more…
                    </li>
                )}
            </ul>
            {changes.length > EXAMPLES && (all ? (
                <button type="button" className="change-identification-show-fewer" aria-expanded={true} onClick={() => setShown(EXAMPLES)}>
                    Show fewer
                    <FontAwesomeIcon icon={faIcon('fass', 'chevron-up')}/>
                </button>
            ) : (
                <button type="button" className="btn change-identification-show-all" aria-expanded={false} onClick={more}>
                    Show all {changes.length.toLocaleString()}
                    <FontAwesomeIcon icon={faIcon('fass', 'chevron-down')}/>
                </button>
            ))}
        </>
    )
}

/** One thing the change does: an icon, what it is, and how many it touches. */
function Step({icon, headline, detail, value, danger = false, children}: {
    icon: IconProp; headline: string; detail: ReactNode; value: number; danger?: boolean; children?: ReactNode
}) {
    return (
        <li className={`change-identification-step${danger ? ' is-danger' : ''}`}>
            <span className="change-identification-step-icon" aria-hidden="true"><FontAwesomeIcon icon={icon}/></span>
            <span className="change-identification-step-text">
                <b>{headline}</b>
                <span>{detail}</span>
            </span>
            <span className="change-identification-step-count">{value.toLocaleString()}</span>
            {children && <div className="change-identification-step-more">{children}</div>}
        </li>
    )
}

const HOW: Record<EpisodeIdentifierValue, string> = {
    date_based: 'by date',
    numbered: 'by number',
    seasonal: 'by season and episode',
}

function defaultOrder(identification: EpisodeIdentifierValue): EpisodeOrderValue {
    return identification === 'seasonal' ? 'oldest_first' : 'newest_first'
}

function count(value: number, one: string, many = `${one}s`) {
    return `${value.toLocaleString()} ${value === 1 ? one : many}`
}

function names(items: string[]) {
    if (items.length <= 1) return items.join('')
    return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`
}

/** Asks before a collection numbers its episodes another way, saying what that does to its files and profiles. */
export default function ChangeIdentificationDialog({
    open, collectionSlug, collectionTitle, current, target, episodeOrder, onDismiss, onStarted,
}: Props) {
    const startOperation = useStartOperation()
    const [error, setError] = useState<string | null>(null)
    const suggestedOrder = target ? defaultOrder(target) : episodeOrder
    // The order follows the identification when the collection still lists its episodes the default way.
    const offerOrder = target !== null && suggestedOrder !== episodeOrder
    const [switchOrder, setSwitchOrder] = useState(true)

    useEffect(() => {
        if (open) {
            setError(null)
            setSwitchOrder(episodeOrder === defaultOrder(current))
        }
    }, [open, target, episodeOrder, current])

    const {data: preview, isLoading, isError} = useQuery({
        queryKey: ['collection', collectionSlug, 'identificationPreview', target],
        enabled: open && target !== null,
        gcTime: 0,
        queryFn: async ({signal}) => {
            const response = await fetch(
                `${apiUrl()}/collections/${encodeURIComponent(collectionSlug)}/episode-identification?episodeIdentifier=${target}`,
                {signal, credentials: 'include'},
            )
            if (!response.ok) throw new Error('Could not look up what the change does')
            return await response.json() as Preview
        },
    })

    const confirm = async () => {
        if (!target || !preview || preview.busy) return
        setError(null)
        try {
            await startOperation(`${apiUrl()}/collections/${encodeURIComponent(collectionSlug)}/episode-identification`, {
                method: 'PUT',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    episodeIdentifier: target,
                    episodeOrder: offerOrder && switchOrder ? suggestedOrder : null,
                }),
            })
            toast.success(`Numbering the episodes of ${collectionTitle} ${HOW[target]}`)
            onStarted()
        } catch (caught) {
            setError(caught instanceof OperationStartError ? caught.message : 'Could not change the episode identification')
        }
    }

    const files = preview?.profiles.reduce((sum, profile) => sum + profile.filesRenamed, 0) ?? 0
    const metadata = preview?.profiles.reduce((sum, profile) => sum + profile.metadataRewritten, 0) ?? 0
    const removed = preview?.downloadProfiles.filter((profile) => profile.removed > 0) ?? []
    const noLongerWanted = preview?.downloadProfiles.filter((profile) => profile.noLongerWanted > 0) ?? []
    const newlyWanted = preview?.downloadProfiles.filter((profile) => profile.newlyWanted > 0) ?? []

    return (
        <ConfirmDialog
            open={open && target !== null}
            title={target ? `Number the episodes ${HOW[target]}?` : ''}
            onDismiss={onDismiss}
            icon={faIcon('fass', 'list-ol')}
            iconTone={removed.length > 0 ? 'danger' : 'default'}
            className="change-identification-dialog"
            confirmButton={{
                // Where "Renumber and rename" would not fit on one line, the button only says "Renumber".
                label: files > 0
                    ? <span>Renumber<span className="change-identification-and-rename"> and rename</span></span>
                    : 'Renumber',
                onClick: confirm,
                className: removed.length > 0 ? 'btn btn-danger' : 'btn btn-primary',
                disabled: !preview || !!preview.busy,
            }}
        >
            {isLoading && (
                <p className="change-identification-loading" role="status">
                    <FontAwesomeIcon icon={faIcon('fass', 'spinner')} spin aria-hidden="true"/>
                    Looking at what changes…
                </p>
            )}
            {isError && <p className="error" role="alert">VODLoft could not look up what the change does.</p>}
            {preview && target && (
                <>
                    <p className="change-identification-change">
                        <span className="change-identification-chip">{EpisodeIdentifierReg.getLabelLoose(current)}</span>
                        <span className="change-identification-arrow" aria-label="to">→</span>
                        <span className="change-identification-chip is-target">{EpisodeIdentifierReg.getLabelLoose(target)}</span>
                    </p>
                    {preview.episodesRenumbered === 0 && <p>The episodes of {collectionTitle} keep their numbers.</p>}
                    <ul className="change-identification-steps">
                        {preview.episodesRenumbered > 0 && (
                            <Step
                                icon={faIcon('fass', 'list-ol')}
                                headline="Episodes get a new number"
                                detail={`of ${count(preview.episodes, 'episode')}${preview.becomeAuxiliary > 0 ? `; ${preview.becomeAuxiliary.toLocaleString()} become auxiliary` : ''}`}
                                value={preview.episodesRenumbered}
                            >
                                {preview.changes.length > 0 && <ChangeList changes={preview.changes}/>}
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
                        {removed.map((profile) => (
                            <Step
                                key={`removed-${profile.name}`}
                                danger
                                icon={faIcon('fass', 'triangle-exclamation')}
                                headline="Downloads deleted"
                                detail={`${profile.name}'s filters leave them out with the new numbers.`}
                                value={profile.removed}
                            />
                        ))}
                        {noLongerWanted.map((profile) => (
                            <Step
                                key={`out-${profile.name}`}
                                icon={faIcon('fass', 'filter')}
                                headline="No longer wanted"
                                detail={`They now fall outside the Download Profile filters for ${profile.name}. They stay on disk until you delete them.`}
                                value={profile.noLongerWanted}
                            />
                        ))}
                        {newlyWanted.map((profile) => (
                            <Step
                                key={`in-${profile.name}`}
                                icon={faIcon('fass', 'download')}
                                headline="Newly wanted"
                                detail={`${profile.name} downloads them with the new numbers.`}
                                value={profile.newlyWanted}
                            />
                        ))}
                    </ul>
                    {offerOrder && (
                        <label className="change-identification-order">
                            <Switch
                                checked={switchOrder}
                                onChange={setSwitchOrder}
                                onColor="#0ea5e9" offColor="#d1d5db" uncheckedIcon={false} checkedIcon={false}
                                height={18} width={34} handleDiameter={14}
                            />
                            <span>
                                <b>List the episodes {EpisodeOrderReg.getLabelLoose(suggestedOrder).toLowerCase()}</b>
                                <span className="help">
                                    {target === 'seasonal'
                                        ? 'A seasonal collection usually starts each season at its first episode.'
                                        : 'A collection numbered this way usually lists its newest episode first.'}
                                </span>
                            </span>
                        </label>
                    )}
                    {preview.busy && <p className="error" role="alert">{preview.busy}</p>}
                    {error && <p className="error" role="alert">{error}</p>}
                    <p className="help">Its progress shows on the collection's page.</p>
                </>
            )}
        </ConfirmDialog>
    )
}
