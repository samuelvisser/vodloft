import {useMemo} from 'react'
import {createSelectRegistry} from '../../utils/selectRegistry'
import type {CreatorRead} from '../../types/schemas/creator'
import type {Names} from '../../types/schemas/source'

/** Where a channel collection goes in the Library: the creator behind its link, new or in the Library already, or
 *  another creator in the Library, such as an artist whose music videos are on their label's channel. */
export const BEHIND_LINK = 'behind'

/** The registry of that choice, in the words of the collection's Site. */
export function useCreatorTargets(key: string, creatorNames: Names | null | undefined, creators: readonly CreatorRead[] | undefined) {
    return useMemo(() => createSelectRegistry<string>(`CreatorTarget-${key}-${creatorNames?.singular}-${creators?.length ?? 0}`, {
        [BEHIND_LINK]: {label: `The ${creatorNames?.singular} behind its link`},
        ...Object.fromEntries((creators ?? []).map((other) => [other.slug, {label: `${other.title} (${other.kind})`}])),
    }), [key, creatorNames, creators])
}
