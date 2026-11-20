import {useState} from 'react'
import {useQueryClient} from '@tanstack/react-query'
import {toast} from 'react-hot-toast'

import {moveCreatorSections} from '../../lib/queries'
import type {CreatorPageRead, SectionMove} from '../../types/schemas/creator'
import MoveSectionsDialog, {type PlaceChange} from './MoveSectionsDialog'
import type {AccountSection} from './CreatorSectionsEditor'

/** A list the creator added that waits for the user's choice. Its videos stay where they would be without it, also
 *  when downloaded, so answering moves them at once: through the same dialog as moving lists on the Edit page, which
 *  also asks before a list keeps its videos out. */
export function isWaitingList({section}: AccountSection): boolean {
    return section.status === 'new' && section.kind === 'list' && !section.collectionSlug
}

/** Answering waiting lists: ``answer`` opens the move dialog for one, and ``dialog`` is that dialog. */
export function useAnswerList(creator: CreatorPageRead) {
    const queryClient = useQueryClient()
    const [answering, setAnswering] = useState<PlaceChange | null>(null)
    const [error, setError] = useState<string | null>(null)

    const answer = (item: AccountSection, move: Omit<SectionMove, 'accountId' | 'ref'>, to: string) => {
        setError(null)
        setAnswering({
            move: {accountId: item.account.id, ref: item.section.ref, ...move},
            title: item.section.title, names: item.section.names,
            from: item.section.status === 'new' ? 'Waiting for your choice' : 'Skipped', to,
        })
    }

    const confirm = async (renumber: Record<string, boolean>) => {
        if (!answering) return
        setError(null)
        try {
            queryClient.setQueryData(['creator', creator.slug], await moveCreatorSections(creator.slug, [answering.move], renumber))
            await Promise.all([
                queryClient.invalidateQueries({queryKey: ['creators']}),
                queryClient.invalidateQueries({queryKey: ['collection']}),
                queryClient.invalidateQueries({queryKey: ['collectionsView']}),
                queryClient.invalidateQueries({queryKey: ['movesWaiting']}),
            ])
            toast.success(answering.move.target === 'keep_out' ? `${answering.title} keeps its videos out` : `Added ${answering.title}`)
            setAnswering(null)
        } catch (exc) {
            setError(exc instanceof Error ? exc.message : String(exc))
        }
    }

    const dialog = (
        <MoveSectionsDialog
            open={answering !== null}
            creatorSlug={creator.slug}
            changes={answering ? [answering] : []}
            onDismiss={() => setAnswering(null)}
            onConfirm={confirm}
            error={error}
        />
    )
    return {answer, dialog}
}
