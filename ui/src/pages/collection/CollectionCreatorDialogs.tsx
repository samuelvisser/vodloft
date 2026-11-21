import type {CollectionWords} from '../../lib/collectionWords'
import {useEffect, useMemo, useState} from 'react'
import {useQuery, useQueryClient} from '@tanstack/react-query'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {toast} from '../../lib/toast'
import ConfirmDialog from '../../components/ConfirmDialog/ConfirmDialog'
import {faIcon} from '../../icons/faIcon'
import {addCollectionToCreator, previewCollectionJoin, setCollectionCreator, useCreators, useCollectionCreatorLeave, useCollectionCreatorMatch} from '../../lib/queries'
import type {CollectionCreatorMatch} from '../../types/schemas/creator'
import type {Names} from '../../types/schemas/source'
import {capitalized} from '../../types/creator'
import SimpleSelect from '../../components/common/SimpleSelect'
import {createSelectRegistry} from '../../utils/selectRegistry'
import LookupSteps from '../creator/LookupSteps'
import {useSlow} from '../../lib/useSlow'
import {CollectionMoves} from '../creator/MoveSectionsDialog'
import '../../components/ChangeIdentificationDialog/ChangeIdentificationDialog.css'
import '../creator/CreatorPages.css'

type DialogProps = {
    open: boolean
    collectionSlug: string
    collectionTitle: string
    /** What the collection's Site calls a creator, such as host on The Daily Wire. */
    /** What the collection calls the creator behind it; there once the collection is loaded from the backend. */
    creatorNames?: Names
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
        const type = creator.sectionTypes.find((type) => type.key === creator.sectionType)
        const kind = type ? `${capitalized(type.names.singular)} · ` : ''
        return `${kind}becomes the ${label}'s ${creator.sectionTitle} section`
    }
    if (creator.keptBy) return `The ${label}'s ${creator.keptBy} has this already, so this collection can't join it`
    return `Not a playlist, show or the videos of this ${label}, so it can't join it`
}

/** "Add to creator", in the words of the Site: find the creator behind the collection's link, show what the collection becomes, and add it. */
export function AddToCreatorDialog({open, collectionSlug, collectionTitle, creatorNames, words, onDismiss, findsCreator = true}: DialogProps & {
    /** What the collection calls its seasons and numbers its episodes by, such as albums and tracks in a Music
     *  collection. */
    words: CollectionWords
}) {
    const {data: libraryCreators} = useCreators()
    /** ``behind``: the creator behind the collection's link; otherwise the slug of a creator in the Library. */
    const [picked, setTarget] = useState<string | null>(null)
    const target = picked ?? (findsCreator ? 'behind' : libraryCreators?.[0]?.slug ?? '')
    const targets = useMemo(() => createSelectRegistry<string>(`JoinCreatorTarget-${collectionSlug}-${findsCreator}`, {
        ...(findsCreator ? {behind: {label: `The ${creatorNames?.singular} behind its link`}} : {}),
        ...Object.fromEntries((libraryCreators ?? []).map((other) => [
            other.slug, {label: `${other.title} (${other.kind})`},
        ])),
    }), [collectionSlug, creatorNames, libraryCreators, findsCreator])
    const chosen = libraryCreators?.find((other) => other.slug === target)
    const match = useCollectionCreatorMatch(collectionSlug, open && target === 'behind')
    // A lookup found already answers in a moment, so its progress only shows once it takes a while.
    const slowMatch = useSlow(match.isLoading)
    const refresh = useRefresh(collectionSlug)
    const creator = match.data
    const matched = !!creator?.sectionTitle
    /** Joining a creator in the Library moves videos between its collections: what moves, before it does. */
    const joinsKnown = !!creator?.creatorSlug && matched
    const moves = useQuery({
        queryKey: ['collection-creator-join-preview', collectionSlug, creator?.lookupId],
        enabled: open && target === 'behind' && joinsKnown,
        gcTime: 0,
        retry: false,
        queryFn: ({signal}) => previewCollectionJoin(collectionSlug, creator?.lookupId, signal),
    })
    const moved = moves.data?.collections ?? []
    const [renumber, setRenumber] = useState<Record<string, boolean>>({})
    useEffect(() => {
        if (open) setRenumber({})
    }, [open])
    const deletes = moved.some((collection) => collection.parts.some((part) => part.downloadsDeleted > 0))

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
            await setCollectionCreator(collectionSlug, true, renumber, creator.lookupId)
            await refresh()
            toast.success(`${collectionTitle} is now part of ${creator.title}`)
            onDismiss()
        } catch (error) {
            toast.error(error instanceof Error ? error.message : `Could not add the collection to the ${creatorNames?.singular}`)
        }
    }

    return (
        <ConfirmDialog
            open={open}
            title={`Add ${collectionTitle} to ${creatorNames?.a}`}
            icon={faIcon('fass', 'circle-user')}
            onDismiss={onDismiss}
            className={!chosen && moved.length > 0 ? 'change-identification-dialog move-sections-dialog' : undefined}
            iconTone={!chosen && deletes ? 'danger' : 'default'}
            confirmButton={{
                label: chosen ? `Add to ${chosen.title}` : creator
                    ? `Add to ${creator.title}${moved.length > 0 ? ' and move' : ''}` : `Add to ${creatorNames?.singular}`,
                onClick: add,
                className: !chosen && deletes ? 'btn btn-danger' : undefined,
                disabled: chosen ? false : !creator || !matched || (joinsKnown && !moves.data),
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
                    <li>{collectionTitle} keeps its own link, so its videos can come from another {creatorNames?.singular} or playlist, such as an artist's music videos on their label's channel.</li>
                    <li>{words.season.Plural}, {words.episode.singular} numbers, profiles and files stay as they are. Nothing is indexed again.</li>
                </ul>
            )}
            {!chosen && slowMatch && (
                <div className="creator-skeleton creator-join" aria-busy="true">
                    <LookupSteps steps={match.steps} first={`Finding the ${creatorNames?.singular} behind the link`}/>
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
                            <span className="creator-kind">{creator.siteName} {creator.creatorNames.singular}</span>
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
                                <span>{sectionNote(creator, creator.creatorNames.singular)}</span>
                            </div>
                        </div>
                    </div>
                    {!matched
                        ? null
                        : !creator.creatorSlug
                            ? (
                                <ul className="creator-order-note">
                                    <li>{words.season.Plural}, {words.episode.singular} numbers, profiles and files stay as they are. Nothing is indexed again.</li>
                                    <li>The {creatorNames?.singular}'s other {creator.sectionGrowingNames.plural} start as not in your library, so you can add them from the {creatorNames?.singular}'s Edit page.</li>
                                </ul>
                            )
                            : (
                                <>
                                    <p className="help">
                                        Each video of {creator.title} is in one of its collections only.
                                        {moved.length > 0
                                            ? ` What another of its collections keeps already moves there, and what ${collectionTitle} takes over moves here, with its files.`
                                            : moves.data ? ` Nothing moves: ${collectionTitle} joins as it is.` : ''}
                                    </p>
                                    {moves.isLoading && (
                                        <p className="change-identification-loading" role="status">
                                            <FontAwesomeIcon icon={faIcon('fass', 'spinner')} spin aria-hidden="true"/>
                                            Looking at what changes…
                                        </p>
                                    )}
                                    {moves.error && (
                                        <p className="error" role="alert">
                                            {moves.error instanceof Error && !(moves.error instanceof TypeError) && moves.error.message
                                                ? moves.error.message : 'VODLoft could not look up what joining moves.'}
                                        </p>
                                    )}
                                    {moved.map((collection) => (
                                        <CollectionMoves
                                            key={collection.slug}
                                            collection={collection}
                                            renumber={renumber[collection.slug] ?? true}
                                            onRenumber={(again) => setRenumber((current) => ({...current, [collection.slug]: again}))}
                                        />
                                    ))}
                                </>
                            )}
                </div>
            )}
        </ConfirmDialog>
    )
}

/** "Remove from creator", in the words of the Site: the collection becomes a plain one again. */
export function RemoveFromCreatorDialog({open, collectionSlug, collectionTitle, creatorNames, onDismiss}: DialogProps) {
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
            toast.error(error instanceof Error ? error.message : `Could not remove the collection from its ${creatorNames?.singular}`)
        }
    }

    return (
        <ConfirmDialog
            open={open}
            title={info ? `Remove from ${info.creatorTitle}?` : `Remove from ${creatorNames?.singular}?`}
            icon={faIcon('fass', 'link-slash')}
            iconTone="danger"
            onDismiss={onDismiss}
            confirmButton={{label: `Remove from ${creatorNames?.singular}`, onClick: remove, className: 'btn btn-danger', disabled: !info}}
        >
            {leave.error && <p className="text-danger">{leave.error.message}</p>}
            <p>
                {collectionTitle} becomes a plain collection. It keeps its episodes, profiles and files, and its genre and
                content rating.
            </p>
        </ConfirmDialog>
    )
}
