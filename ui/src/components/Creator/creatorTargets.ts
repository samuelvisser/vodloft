import {useMemo} from 'react'
import {createSelectRegistry} from '../../utils/selectRegistry'
import type {CreatorRead} from '../../types/schemas/creator'
import type {Names} from '../../types/schemas/source'

/** Where a collection goes in the Library: the creator behind its link, new or in the Library already, such as the
 *  channel that made a playlist, or another creator in the Library, such as an artist whose music videos are on their
 *  label's channel. */
export const BEHIND_LINK = 'behind'

/** The registry of that choice, in the words of the collection's Site. A collection without a link of its own has
 *  no creator behind it, so ``behindLink`` false leaves only the creators in the Library. */
export function useCreatorTargets(
    key: string, creatorNames: Names | null | undefined, creators: readonly CreatorRead[] | undefined, behindLink = true,
) {
    return useMemo(() => createSelectRegistry<string>(`CreatorTarget-${key}-${creatorNames?.singular}-${creators?.length ?? 0}-${behindLink}`, {
        ...(behindLink ? {[BEHIND_LINK]: {label: `The ${creatorNames?.singular} behind its link`}} : {}),
        ...Object.fromEntries((creators ?? []).map((other) => [other.slug, {label: `${other.title} (${other.kind})`}])),
    }), [key, creatorNames, creators, behindLink])
}
