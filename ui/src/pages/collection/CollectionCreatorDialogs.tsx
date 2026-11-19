import {useMemo, useState} from 'react'
import {useQueryClient} from '@tanstack/react-query'
import {toast} from 'react-hot-toast'
import ConfirmDialog from '../../components/ConfirmDialog/ConfirmDialog'
import {faIcon} from '../../icons/faIcon'
import {addCollectionToCreator, setCollectionCreator, useCreators, useCollectionCreatorLeave, useCollectionCreatorMatch} from '../../lib/queries'
import type {CollectionCreatorMatch} from '../../types/schemas/creator'
import SimpleSelect from '../../components/common/SimpleSelect'
import {createSelectRegistry} from '../../utils/selectRegistry'
import LookupSteps from '../creator/LookupSteps'
import '../creator/CreatorPages.css'

type DialogProps = {
    open: boolean
    collectionSlug: string
    collectionTitle: string
    /** What the collection's Site calls a creator, such as host on The Daily Wire. */
    creatorLabel: string
    onDismiss: () => void
    /** The collection's Source can find the creator behind its link. Without it, it joins a creator in the Library. */
    findsCreator?: boolean
}

function useRefresh(collectionSlug: string) {
    const queryClient = useQueryClient()
    return async () => {
        await Promise.all([
            queryClient.invalidateQueries({queryKey: ['collection', collectionSlug]}),
            queryClient.invalidateQueries({queryKey: ['collections']}),
            queryClient.invalidateQueries({queryKey: ['creators']}),
            queryClient.invalidateQueries({queryKey: ['creator']}),
            queryClient.removeQueries({queryKey: ['collection-creator-match', collectionSlug]}),
            queryClient.removeQueries({queryKey: ['collection-creator-leave', collectionSlug]}),
        ])
    }
}

function sectionNote(creator: CollectionCreatorMatch, label: string): string {
    if (creator.sectionTitle) {
        const kind = creator.sectionKindLabel ? `${creator.sectionKindLabel} · ` : ''
        return `${kind}becomes the ${label}'s ${creator.sectionTitle} section`
    }
    if (creator.keptBy) return `The ${label}'s ${creator.keptBy} has this already, so this collection can't join it`
    return `Not a playlist, show or the videos of this ${label}, so it can't join it`
}

/** "Add to creator", in the words of the Site: find the creator behind the collection's link, show what the collection becomes, and add it. */
export function AddToCreatorDialog({open, collectionSlug, collectionTitle, creatorLabel, onDismiss, findsCreator = true}: DialogProps) {
    const {data: libraryCreators} = useCreators()
    /** ``behind``: the creator behind the collection's link; otherwise the slug of a creator in the Library. */
    const [picked, setTarget] = useState<string | null>(null)
    const target = picked ?? (findsCreator ? 'behind' : libraryCreators?.[0]?.slug ?? '')
    const targets = useMemo(() => createSelectRegistry<string>(`JoinCreatorTarget-${collectionSlug}-${findsCreator}`, {
        ...(findsCreator ? {behind: {label: `The ${creatorLabel} behind its link`}} : {}),
        ...Object.fromEntries((libraryCreators ?? []).map((other) => [
            other.slug, {label: `${other.title} (${other.kind})`},
        ])),
    }), [collectionSlug, creatorLabel, libraryCreators, findsCreator])
    const chosen = libraryCreators?.find((other) => other.slug === target)
    const match = useCollectionCreatorMatch(collectionSlug, open && target === 'behind')
    const refresh = useRefresh(collectionSlug)
    const creator = match.data
    const matched = !!creator?.sectionTitle
    /** The overlapping playlists the user moves here; the rest stay where they are. */
    const [moveHere, setMoveHere] = useState<Set<string>>(new Set())

    const addElsewhere = async () => {
        if (!chosen) return
        try {
            await addCollectionToCreator(collectionSlug, chosen.slug)
            await refresh()
            toast.success(`${collectionTitle} is now part of ${chosen.title}`)
            onDismiss()
        } catch (error) {
            toast.error(error instanceof Error ? error.message : `Could not add the collection to ${chosen.title}`)
        }
    }

    const add = async () => {
        if (chosen) return addElsewhere()
        if (!creator) return
        try {
            await setCollectionCreator(collectionSlug, true, [...moveHere].filter((ref) => (
                creator.overlaps.some((overlap) => overlap.ref === ref && overlap.canMoveHere)
            )), creator.lookupId)
            await refresh()
            toast.success(`${collectionTitle} is now part of ${creator.title}`)
            onDismiss()
        } catch (error) {
            toast.error(error instanceof Error ? error.message : `Could not add the collection to the ${creatorLabel}`)
        }
    }

    return (
        <ConfirmDialog
            open={open}
            title={`Add ${collectionTitle} to a ${creatorLabel}`}
            icon={faIcon('fass', 'circle-user')}
            onDismiss={onDismiss}
            confirmButton={{
                label: chosen ? `Add to ${chosen.title}` : creator ? `Add to ${creator.title}` : `Add to ${creatorLabel}`,
                onClick: add,
                disabled: chosen ? false : !creator || !matched,
            }}
        >
            {(libraryCreators?.length ?? 0) > 0 && (
                <div className="form-row">
                    <label htmlFor="join-creator-target">Add it to</label>
                    <SimpleSelect
                        inputId="join-creator-target" registry={targets} value={target}
                        menuPortalTarget={document.body} menuPlacement="auto"
                        styles={{menuPortal: (base) => ({...base, zIndex: 1100})}}
                        onChange={setTarget}
                    />
                </div>
            )}
            {chosen && (
                <ul className="creator-order-note">
                    <li>{collectionTitle} keeps its own link, so its videos can come from another {creatorLabel} or playlist, such as an artist's music videos on their label's channel.</li>
                    <li>Seasons, episode numbers, profiles and files stay as they are. Nothing is indexed again.</li>
                </ul>
            )}
            {!chosen && match.isLoading && (
                <div className="creator-skeleton creator-join" aria-busy="true">
                    <LookupSteps steps={match.steps} first={`Finding the ${creatorLabel} behind the link`}/>
                    <div className="creator-join-who" aria-hidden="true">
                        <span className="creator-avatar creator-avatar--small skeleton-block"/>
                        <div className="creator-skeleton-copy">
                            <span className="skeleton-block creator-skeleton-line creator-skeleton-line--kind"/>
                            <span className="skeleton-block creator-skeleton-line creator-skeleton-line--title-small"/>
                            <span className="skeleton-block creator-skeleton-line creator-skeleton-line--short"/>
                        </div>
                    </div>
                    <div className="creator-section-list" aria-hidden="true">
                        <div className="creator-section-row">
                            <div className="creator-section-copy creator-skeleton-copy">
                                <span className="skeleton-block creator-skeleton-line creator-skeleton-line--title-small"/>
                                <span className="skeleton-block creator-skeleton-line"/>
                            </div>
                        </div>
                    </div>
                </div>
            )}
            {!chosen && match.error && <p className="text-danger">{match.error.message}</p>}
            {!chosen && creator && (
                <div className="creator-join">
                    <div className="creator-join-who">
                        {creator.avatarUrl
                            ? <img className="creator-avatar creator-avatar--small" src={creator.avatarUrl} alt="" loading="lazy"/>
                            : <span className="creator-avatar creator-avatar--small creator-avatar--empty" aria-hidden="true">{creator.title.slice(0, 1)}</span>}
                        <div className="creator-identity-copy">
                            <span className="creator-kind">{creator.siteName} {creator.creatorLabel}</span>
                            <strong>{creator.title}</strong>
                            <span className="creator-section-note">
                                {creator.creatorSlug ? 'In your library.' : 'Not in your library yet. It will be added.'}
                            </span>
                        </div>
                    </div>
                    <div className="creator-section-list">
                        <div className="creator-section-row">
                            <div className="creator-section-copy">
                                <strong>{collectionTitle}</strong>
                                <span>{sectionNote(creator, creatorLabel)}</span>
                            </div>
                        </div>
                    </div>
                    {matched && creator.overlaps.length > 0 && (
                        <div className="creator-join-overlaps">
                            <p>
                                These playlists of {collectionTitle} are also somewhere else in
                                the {creatorLabel}. Once it joins, each is in one place only.
                            </p>
                            {creator.overlaps.map((overlap) => (
                                <OverlapChoice
                                    key={overlap.ref} title={overlap.title} keptBy={overlap.keptBy}
                                    collectionTitle={collectionTitle} canMoveHere={overlap.canMoveHere}
                                    fitLabels={creator.overlaps.flatMap((item) => overlapLabels(item.keptBy, collectionTitle))}
                                    movesHere={moveHere.has(overlap.ref)}
                                    onChange={(here) => setMoveHere((current) => {
                                        const next = new Set(current)
                                        if (here) next.add(overlap.ref)
                                        else next.delete(overlap.ref)
                                        return next
                                    })}
                                />
                            ))}
                        </div>
                    )}
                    {!matched
                        ? null
                        : (
                            <ul className="creator-order-note">
                                <li>Seasons, episode numbers, profiles and files stay as they are. Nothing is indexed again.</li>
                                {!creator.creatorSlug && <li>The {creatorLabel}'s other {creator.sectionNames.many} start as not in your library, so you can add them from the {creatorLabel}'s Edit page.</li>}
                            </ul>
                        )}
                </div>
            )}
        </ConfirmDialog>
    )
}

/** Where a playlist that is in two places can go, in words. */
function overlapLabels(keptBy: string, collectionTitle: string): [string, string] {
    return [`Stays in ${keptBy}`, `Moves to ${collectionTitle}`]
}

/** Where one playlist that is in two places goes once the collection joins its creator. */
function OverlapChoice({title, keptBy, collectionTitle, canMoveHere, movesHere, fitLabels, onChange}: {
    title: string, keptBy: string, collectionTitle: string, canMoveHere: boolean, movesHere: boolean,
    fitLabels: readonly string[], onChange: (here: boolean) => void,
}) {
    const registry = useMemo(() => {
        const [stays, here] = overlapLabels(keptBy, collectionTitle)
        return createSelectRegistry(`JoinOverlap-${keptBy}-${collectionTitle}`, {stays: {label: stays}, here: {label: here}})
    }, [keptBy, collectionTitle])
    const inputId = `join-overlap-${title}`
    return (
        <div className="creator-section-row">
            <div className="creator-section-copy">
                <strong>{title}</strong>
                {!canMoveHere && <span>Stays in {keptBy}, a collection of its own. It leaves {collectionTitle}.</span>}
            </div>
            {canMoveHere && (
                <div className="creator-join-overlap-select">
                    <label className="sr-only" htmlFor={inputId}>Where {title} goes</label>
                    <SimpleSelect
                        inputId={inputId} registry={registry} value={movesHere ? 'here' : 'stays'} fitLabels={fitLabels}
                        menuPortalTarget={document.body} menuPlacement="auto"
                        styles={{menuPortal: (base) => ({...base, zIndex: 1100})}}
                        onChange={(value) => onChange(value === 'here')}
                    />
                </div>
            )}
        </div>
    )
}

/** "Remove from creator", in the words of the Site: the collection becomes a plain one again. */
export function RemoveFromCreatorDialog({open, collectionSlug, collectionTitle, creatorLabel, onDismiss}: DialogProps) {
    const leave = useCollectionCreatorLeave(collectionSlug, open)
    const refresh = useRefresh(collectionSlug)
    const info = leave.data

    const remove = async () => {
        try {
            await setCollectionCreator(collectionSlug, false)
            await refresh()
            toast.success(`${collectionTitle} is a plain collection now`)
            onDismiss()
        } catch (error) {
            toast.error(error instanceof Error ? error.message : `Could not remove the collection from its ${creatorLabel}`)
        }
    }

    return (
        <ConfirmDialog
            open={open}
            title={info ? `Remove from ${info.creatorTitle}?` : `Remove from ${creatorLabel}?`}
            icon={faIcon('fass', 'link-slash')}
            iconTone="danger"
            onDismiss={onDismiss}
            confirmButton={{label: `Remove from ${creatorLabel}`, onClick: remove, className: 'btn btn-danger', disabled: !info}}
        >
            {leave.error && <p className="text-danger">{leave.error.message}</p>}
            <p>
                {collectionTitle} becomes a plain collection. It keeps its episodes, profiles and files, and its genre and
                content rating.
            </p>
        </ConfirmDialog>
    )
}
