import {useState} from 'react'
import {useQueryClient} from '@tanstack/react-query'
import {toast} from '../../lib/toast'
import ConfirmDialog from '../../components/ConfirmDialog/ConfirmDialog'
import {faIcon} from '../../icons/faIcon'
import {addCollectionToCreator, setCollectionCreator, useCreators, useCollectionCreatorMatch} from '../../lib/queries'
import type {Names} from '../../types/schemas/source'
import SimpleSelect from '../../components/common/SimpleSelect'
import {BEHIND_LINK, useCreatorTargets} from '../../components/Creator/creatorTargets'
import LookupSteps from '../creator/LookupSteps'
import {useSlow} from '../../lib/useSlow'
import '../creator/CreatorPages.css'
import {nameInText} from '../../lib/nameInText'

type DialogProps = {
    open: boolean
    collectionSlug: string
    collectionTitle: string
    /** What the collection calls the creator behind it; there once the collection is loaded from the backend. */
    creatorNames?: Names
    onDismiss: () => void
}

function useRefresh(collectionSlug: string) {
    const queryClient = useQueryClient()
    return async () => {
        await Promise.all([
            queryClient.invalidateQueries({queryKey: ['collection', collectionSlug]}),
            queryClient.invalidateQueries({queryKey: ['collections']}),
            queryClient.invalidateQueries({queryKey: ['collectionsView']}),
            queryClient.invalidateQueries({queryKey: ['creators']}),
            queryClient.invalidateQueries({queryKey: ['creator']}),
            queryClient.removeQueries({queryKey: ['collection-creator-match', collectionSlug]}),
        ])
    }
}

/** "Add to creator", in the words of the Site: group the collection under the creator behind its link, such as the
 *  channel that made a playlist, or another creator in the Library. A collection without a link of its own can only
 *  join one in the Library. Nothing the collection holds changes. */
export function AddToCreatorDialog({open, collectionSlug, collectionTitle, creatorNames, hasLink, onDismiss}: DialogProps & {
    /** The collection has a link of its own, with a creator behind it to suggest. */
    hasLink: boolean
}) {
    const {data: libraryCreators} = useCreators()
    const [picked, setTarget] = useState<string | null>(null)
    const target = picked ?? (hasLink ? BEHIND_LINK : libraryCreators?.[0]?.slug ?? '')
    const targets = useCreatorTargets(collectionSlug, creatorNames, libraryCreators, hasLink)
    const chosen = libraryCreators?.find((other) => other.slug === target)
    const match = useCollectionCreatorMatch(collectionSlug, open && hasLink && target === BEHIND_LINK)
    // A lookup found already answers in a moment, so its progress only shows once it takes a while.
    const slowMatch = useSlow(match.isLoading)
    const refresh = useRefresh(collectionSlug)
    const creator = match.data
    const intoTitle = chosen?.title ?? creator?.creatorTitle ?? creator?.title
    const into = intoTitle ? nameInText(intoTitle) : undefined

    const add = async () => {
        try {
            if (chosen) await addCollectionToCreator(collectionSlug, chosen.slug)
            else await setCollectionCreator(collectionSlug, true, creator?.lookupId)
            await refresh()
            toast.success(`${nameInText(collectionTitle)} is now part of ${into}`)
            onDismiss()
        } catch (error) {
            toast.error(error instanceof Error ? error.message : `Could not add the collection to the ${creatorNames?.singular}`)
        }
    }

    return (
        <ConfirmDialog
            open={open}
            title={`Add ${nameInText(collectionTitle)} to ${creatorNames?.a}`}
            icon={faIcon('fass', 'circle-user')}
            onDismiss={onDismiss}
            confirmButton={{
                label: into ? `Add to ${into}` : `Add to ${creatorNames?.singular}`,
                onClick: add,
                disabled: !chosen && !creator,
            }}
        >
            {(libraryCreators?.length ?? 0) > 0 && (
                <div className="form-row">
                    <label htmlFor="join-creator-target">Add it to</label>
                    <SimpleSelect
                        inputId="join-creator-target" registry={targets} value={target}
                        menuPortalTarget={document.body} menuPlacement="auto"
                        styles={{menuPortal: (base) => ({...base, zIndex: 1100})}}
                        onChange={(value) => setTarget(value ?? null)}
                    />
                </div>
            )}
            {!hasLink && libraryCreators?.length === 0 && (
                <p>
                    {nameInText(collectionTitle)} has no link of its own to find {creatorNames?.a} behind. Add
                    the {creatorNames?.singular} to your library first, then add the collection to them here.
                </p>
            )}
            {!chosen && hasLink && slowMatch && (
                <div className="creator-skeleton creator-join" aria-busy="true">
                    <LookupSteps steps={match.steps} first={`Finding the ${creatorNames?.singular} behind the link`}/>
                    <div className="creator-join-who" aria-hidden="true">
                        <span className="creator-avatar creator-avatar--small skeleton-block"/>
                        <div className="creator-skeleton-copy">
                            <span className="skeleton-block creator-skeleton-line creator-skeleton-line--kind"/>
                            <span className="skeleton-block creator-skeleton-line creator-skeleton-line--title-small"/>
                        </div>
                    </div>
                </div>
            )}
            {!chosen && hasLink && match.error && <p className="text-danger">{match.error.message}</p>}
            {!chosen && hasLink && creator && (
                <div className="creator-join">
                    <div className="creator-join-who">
                        {creator.avatarUrl
                            ? <img className="creator-avatar creator-avatar--small" src={creator.avatarUrl} alt="" loading="lazy"/>
                            : <span className="creator-avatar creator-avatar--small creator-avatar--empty" aria-hidden="true">{creator.title.slice(0, 1)}</span>}
                        <div className="creator-identity-copy">
                            <span className="creator-kind">{creator.siteName} {creator.creatorNames.singular}</span>
                            <strong>{creator.creatorTitle ?? creator.title}</strong>
                            <span className="creator-section-note">
                                {creator.creatorSlug ? 'In your library.' : 'Not in your library yet. It will be added.'}
                            </span>
                        </div>
                    </div>
                </div>
            )}
            <p className="help">
                The {creatorNames?.singular} groups {nameInText(collectionTitle)} with their other collections in your library.
                Nothing in {nameInText(collectionTitle)} changes.
            </p>
        </ConfirmDialog>
    )
}

/** "Remove from creator", in the words of the Site: the collection stands on its own in the Library again. */
export function RemoveFromCreatorDialog({open, collectionSlug, collectionTitle, creatorNames, creatorTitle, onDismiss}: DialogProps & {
    creatorTitle?: string | null
}) {
    const refresh = useRefresh(collectionSlug)

    const remove = async () => {
        try {
            await setCollectionCreator(collectionSlug, false)
            await refresh()
            toast.success(`${nameInText(collectionTitle)} is no longer part of ${creatorTitle ? nameInText(creatorTitle) : `its ${creatorNames?.singular}`}`)
            onDismiss()
        } catch (error) {
            toast.error(error instanceof Error ? error.message : `Could not remove the collection from its ${creatorNames?.singular}`)
        }
    }

    return (
        <ConfirmDialog
            open={open}
            title={`Remove from ${creatorTitle ? nameInText(creatorTitle) : creatorNames?.singular}?`}
            icon={faIcon('fass', 'link-slash')}
            onDismiss={onDismiss}
            confirmButton={{label: `Remove from ${creatorNames?.singular}`, onClick: remove}}
        >
            <p>
                {nameInText(collectionTitle)} stands on its own in your library again. Nothing in it changes: it keeps its episodes,
                profiles and files, and its genre and content rating.
            </p>
        </ConfirmDialog>
    )
}
