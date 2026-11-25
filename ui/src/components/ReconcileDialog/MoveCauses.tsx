import type {ComponentType} from 'react'
import {useQuery} from '@tanstack/react-query'
import {Link} from 'react-router-dom'

import {apiUrl} from '../../lib/api'
import {wordsOf} from '../../lib/collectionWords'
import {capitalized} from '../../types/creator'
import type {CollectionSeasonsRead} from '../../types/schemas/collection_seasons'
import type {MoveCause, MoveCauseOrigin} from '../../types/schemas/reconcile'
import {ChangeChips, names} from '../ChangeIdentificationDialog/ChangeSteps'
import {dialogWords, namesOf, readSeasons, registries} from '../CollectionSeasons/seasonsSettings'

/** Why the Move dialog moves what it moves: the setting changes that put the downloads in another season, each as
 * it was and is now. Every origin of such changes, such as the Seasons dialog, names its settings and their values in
 * its own words, with a way back to where they are changed; the dialog shows them all, in the order they were made. */

type OriginProps = {collectionSlug: string, causes: MoveCause[]}

/** One change: what the setting is, and its value before and now. */
type CauseRow = {key: string, setting: string, before: string, after: string}

const ORIGINS: Record<MoveCauseOrigin, ComponentType<OriginProps>> = {
    seasons: SeasonsCauses,
}

export default function MoveCauses({collectionSlug, causes}: OriginProps) {
    const origins = [...new Set(causes.map((cause) => cause.origin))]
    return (
        <>
            {origins.map((origin) => {
                const Origin = ORIGINS[origin]
                return <Origin key={origin} collectionSlug={collectionSlug} causes={causes.filter((cause) => cause.origin === origin)}/>
            })}
        </>
    )
}

function CauseRows({rows}: {rows: CauseRow[]}) {
    return (
        <ul className="move-causes" aria-label="What changed">
            {rows.map((row) => (
                <li key={row.key}>
                    <span className="move-cause-setting">{row.setting}</span>
                    <ChangeChips before={row.before} after={row.after}/>
                </li>
            ))}
        </ul>
    )
}

/** Changes in the collection's Seasons dialog, named as that dialog names its settings. */
function SeasonsCauses({collectionSlug, causes}: OriginProps) {
    const {data: view} = useQuery({
        queryKey: ['collection', collectionSlug, 'seasonSettings'],
        queryFn: ({signal}) => fetch(
            `${apiUrl()}/collections/${encodeURIComponent(collectionSlug)}/season-settings`, {signal, credentials: 'include'},
        ).then(readSeasons),
    })
    if (!view) return null
    const rows = seasonsRows(view, causes)
    const {season} = wordsOf(view.words)
    return (
        <>
            <CauseRows rows={rows}/>
            <p className="help move-reason">
                Not what you want? Change it back under{' '}
                <Link to={`/edit-collection/${encodeURIComponent(collectionSlug)}?seasons=1`}>{season.Plural}</Link>
                {' '}instead of moving them.
            </p>
        </>
    )
}

function seasonsRows(view: CollectionSeasonsRead, causes: MoveCause[]): CauseRow[] {
    const words = dialogWords(wordsOf(view.words), view)
    const lists = namesOf(view, view.looseSeason)
    const regs = registries(lists, words, view)
    const only = view.outsideVideos === 'only'
    const text = (value: MoveCause['before']) => Array.isArray(value) ? value.join(', ') : value ?? ''
    const feeds = (value: MoveCause['before']) => {
        const on = view.feeds.filter((feed) => value === null || (Array.isArray(value) && value.includes(feed.ref)))
        return on.length ? names(on.map((feed) => capitalized(feed.names.plural))) : 'None'
    }
    const list = (value: MoveCause['before']) => value === 'off'
        ? 'Off' : only ? 'On' : regs.placement.getLabelLoose(text(value))
    const settings: Record<string, {setting: string, value: (value: MoveCause['before']) => string}> = {
        link_seasons: {
            setting: view.siteOrder ? capitalized(lists.plural) : `${capitalized(lists.plural)} as ${words.season.plural}`,
            value: (value) => value === 'off' ? 'Off' : regs.mode.getLabelLoose(text(value)),
        },
        outside_videos: {
            setting: `How ${lists.singular} content fits in the collection`,
            value: (value) => regs.outside.getLabelLoose(text(value)),
        },
        list_layout: {setting: `Where the ${lists.plural} go`, value: (value) => regs.layout.getLabelLoose(text(value))},
        loose_videos: {
            setting: `How VODLoft groups the ${words.videos}`,
            value: (value) => view.madeFromList ? regs.listSeasons.getLabelLoose(text(value))
                : view.linkSeasons === 'selected' || (view.linkSeasons === 'all' && (view.listsAsSeasons || only))
                    ? regs.channelWithLists.getLabelLoose(text(value))
                    // With no lists as seasons, the one season holds the whole channel.
                    : regs.channel.getLabelLoose(value === 'one_season' ? 'everything' : text(value)),
        },
        repeat_videos: {
            setting: `When ${words.episode.a} belongs ${words.inSeason} several ${words.season.plural}`,
            value: (value) => regs.repeat.getLabelLoose(text(value)),
        },
        feeds: {setting: 'Feeds', value: feeds},
        lists_as_seasons: {
            setting: `How the ${lists.plural} are included`,
            value: (value) => regs.listsAs.getLabelLoose(text(value)),
        },
    }
    return causes.flatMap((cause) => {
        const known = cause.setting === 'list'
            ? {setting: cause.subjectTitle ?? capitalized(lists.singular), value: list}
            : settings[cause.setting]
        if (!known) return []
        return [{
            key: `${cause.setting}-${cause.subjectId ?? ''}`, setting: known.setting,
            before: known.value(cause.before), after: known.value(cause.after),
        }]
    })
}
