import {useCallback, useMemo, useState} from 'react'
import {useProfileTableIds} from '../../lib/queries'

/**
 * Bulk edit on a profile table: whether it is on, and which profiles are chosen. While it is on, it loads the ids
 * of every profile the filters match, loaded in the table or not, so Select all takes them all. A profile chosen
 * before the filters changed stays chosen, and ``hidden`` counts those the filters now leave out.
 */
export function useBulkSelection(
    tablePrefix: string,
    path: string,
    filters: Parameters<typeof useProfileTableIds>[2],
) {
    const [active, setActive] = useState(false)
    const matchingIds = useProfileTableIds(tablePrefix, path, filters, active).data?.ids
    const [selected, setSelected] = useState<ReadonlySet<number>>(new Set())

    const matching = useMemo(() => new Set(matchingIds ?? []), [matchingIds])
    const selectedMatching = useMemo(() => [...selected].filter((id) => matching.has(id)).length, [selected, matching])
    const allState: 'none' | 'some' | 'all' = selectedMatching === 0
        ? 'none'
        : selectedMatching === matching.size ? 'all' : 'some'

    const toggle = useCallback((id: number) => setSelected((current) => {
        const next = new Set(current)
        if (next.has(id)) next.delete(id)
        else next.add(id)
        return next
    }), [])

    const toggleAll = useCallback(() => setSelected((current) => {
        const next = new Set(current)
        const everyOne = [...matching].every((id) => next.has(id))
        for (const id of matching) {
            if (everyOne) next.delete(id)
            else next.add(id)
        }
        return next
    }), [matching])

    const clear = useCallback(() => setSelected(new Set()), [])
    const start = useCallback(() => setActive(true), [])
    const stop = useCallback(() => {
        setActive(false)
        setSelected(new Set())
    }, [])

    return {
        active,
        start,
        stop,
        selected,
        ids: useMemo(() => [...selected], [selected]),
        toggle,
        toggleAll,
        clear,
        allState,
        /** How many profiles the filters match, once known. */
        matchingCount: matchingIds?.length,
        hidden: matchingIds === undefined ? 0 : selected.size - selectedMatching,
    }
}

export type BulkSelection = ReturnType<typeof useBulkSelection>
