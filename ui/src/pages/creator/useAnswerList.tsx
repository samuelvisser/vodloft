import {useState} from 'react'
import {useQueryClient} from '@tanstack/react-query'
import {toast} from '../../lib/toast'

import {moveCreatorSections} from '../../lib/queries'
import type {CreatorPageRead, SectionMove} from '../../types/schemas/creator'
import MoveSectionsDialog, {type PlaceChange} from './MoveSectionsDialog'
import type {AccountSection} from './CreatorSectionsEditor'
import {SECTION_ACTIONS} from './sectionActions'

/** A list of the creator that is not in the Library: one that waits for the user's choice, or one they skipped or
 *  keep out. Its videos stay where the creator's other feeds and lists put them, also when downloaded, so adding it
 *  moves them at once: through the same dialog as moving lists on the Edit page, which first says what leaves each
 *  collection, and also asks before a list keeps its videos out. */
export function isListOutside({section}: AccountSection): boolean {
    return section.kind === 'list' && !section.collectionSlug
}

/** Answering waiting lists: ``answer`` opens the move dialog for one, ``answerAll`` for several at once, as the bulk
 *  bar does, and ``dialog`` is that dialog. ``onAnswered`` hears which lists were answered. */
export function useAnswerList(creator: CreatorPageRead, onAnswered?: (items: AccountSection[]) => void) {
    const queryClient = useQueryClient()
    const [answering, setAnswering] = useState<{changes: PlaceChange[], items: AccountSection[]} | null>(null)
    const [error, setError] = useState<string | null>(null)

    const change = (item: AccountSection, move: Omit<SectionMove, 'accountId' | 'ref'>, to: string): PlaceChange => ({
        move: {accountId: item.account.id, ref: item.section.ref, ...move},
        title: item.section.title, names: item.section.names,
        from: item.section.status === 'new' ? 'Waiting for your choice' : item.section.status === 'kept_out' ? SECTION_ACTIONS.keepOut : SECTION_ACTIONS.skip, to,
    })

    const answer = (item: AccountSection, move: Omit<SectionMove, 'accountId' | 'ref'>, to: string) => answerAll([item], move, to)

    const answerAll = (items: AccountSection[], move: Omit<SectionMove, 'accountId' | 'ref'>, to: string | ((item: AccountSection) => string)) => {
        if (!items.length) return
        setError(null)
        setAnswering({items, changes: items.map((item) => change(item, move, typeof to === 'string' ? to : to(item)))})
    }

    const confirm = async (renumber: Record<string, boolean>) => {
        if (!answering) return
        setError(null)
        try {
            queryClient.setQueryData(['creator', creator.slug], await moveCreatorSections(
                creator.slug, answering.changes.map((one) => one.move), renumber,
            ))
            await Promise.all([
                queryClient.invalidateQueries({queryKey: ['creators']}),
                queryClient.invalidateQueries({queryKey: ['collection']}),
                queryClient.invalidateQueries({queryKey: ['collectionsView']}),
                queryClient.invalidateQueries({queryKey: ['movesWaiting']}),
            ])
            const [first] = answering.changes
            const named = answering.changes.length === 1 ? first.title : `${answering.changes.length} ${first.names.plural}`
            toast.success(first.move.target === 'keep_out'
                ? `${named} ${answering.changes.length === 1 ? 'keeps its' : 'keep their'} videos out` : `Added ${named}`)
            onAnswered?.(answering.items)
            setAnswering(null)
        } catch (exc) {
            setError(exc instanceof Error ? exc.message : String(exc))
        }
    }

    const dialog = (
        <MoveSectionsDialog
            open={answering !== null}
            creatorSlug={creator.slug}
            changes={answering?.changes ?? []}
            onDismiss={() => setAnswering(null)}
            onConfirm={confirm}
            error={error}
        />
    )
    return {answer, answerAll, dialog}
}
