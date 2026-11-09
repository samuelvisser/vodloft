/**
 * The sentences of Which episodes. Each filter reads as a sentence, with the
 * values that matter in bold.
 */
import {describeMatch} from '../RegexEditor/regexModel'
import {isDateLine, splitIgnoreCase, type FilterLike} from './episodeFilters'

/** A piece of a sentence; strong pieces are the values you chose. */
export type Part = {text: string; strong?: boolean; code?: boolean}

const ACTION_WORDS: Record<string, string> = {
    skip: 'Skip if the',
    only: 'Only download if the',
    keep: 'Keep if the',
}

const UNITS: Array<[number, string]> = [[86_400, 'day'], [3_600, 'hour'], [60, 'minute'], [1, 'second']]

/** An episode's length in short, such as "1 h 4 min" or "45 sec". */
export function formatRunningTime(seconds: number): string {
    const total = Math.max(0, Math.round(seconds))
    if (total < 60) return `${total} sec`
    const allMinutes = Math.round(total / 60)
    const hours = Math.floor(allMinutes / 60)
    const minutes = allMinutes % 60
    if (!hours) return `${minutes} min`
    return minutes ? `${hours} h ${minutes} min` : `${hours} h`
}

/** A length in seconds as words, such as "1 hour 30 minutes". */
export function formatDuration(seconds: number): string {
    let rest = Math.max(0, Math.round(seconds))
    const words: string[] = []
    for (const [size, unit] of UNITS) {
        const amount = Math.floor(rest / size)
        if (amount > 0) {
            words.push(`${amount} ${unit}${amount === 1 ? '' : 's'}`)
            rest -= amount * size
        }
    }
    return words.length ? words.join(' ') : '0 seconds'
}

/** Whether a filter says enough to count which episodes it leaves out. */
export function filterComplete(filter: FilterLike): boolean {
    if (filter.field === 'types') return !!filter.episodeTypes?.length
    if (filter.field === 'seasons') return !!filter.seasonSlugs?.length || !!filter.includeUpcoming
    if (filter.field === 'duration') return !!filter.durationSeconds && !!filter.durationOperator
    if (filter.field === 'published') return !!filter.days || !!filter.count || !!filter.startingFrom
    if (filter.field === 'downloaded') return !!filter.days
    return !!splitIgnoreCase(filter.pattern).pattern
}

function plural(amount: number, unit: string): string {
    return `${amount} ${unit}${amount === 1 ? '' : 's'}`
}

function sinceDays(days: number, today: Date): string {
    const since = new Date(today)
    since.setHours(0, 0, 0, 0)
    since.setDate(since.getDate() - days)
    return shortDate(since)
}

/** A date line: "Only download the latest 25 episodes, and delete older ones". */
function dateLineSentence(filter: FilterLike, deleteOlder: boolean, today: Date): Part[] {
    const only = filter.action === 'only'
    const days = filter.days ?? 0
    if (filter.field === 'downloaded') {
        if (!only) return [{text: 'Keep downloads for '}, {text: days ? plural(days, 'day') : '…', strong: true}, {text: ' after downloading'}]
        const parts: Part[] = [
            {text: 'Only download episodes published in the '},
            {text: days ? `last ${plural(days, 'day')}` : 'last … days', strong: true},
        ]
        if (days && deleteOlder) parts.push({text: `, and delete them ${plural(days, 'day')} after downloading`})
        return parts
    }
    const lead = only ? 'Only download ' : 'Keep '
    if (filter.count) {
        const parts: Part[] = [{text: `${lead}the `}, {text: `latest ${filter.count}`, strong: true}, {text: filter.count === 1 ? ' episode' : ' episodes'}]
        if (only && deleteOlder) parts.push({text: ', and delete older ones'})
        return parts
    }
    if (days) {
        const parts: Part[] = [
            {text: `${lead}episodes published in the `},
            {text: `last ${plural(days, 'day')}`, strong: true},
            {text: ` (since ${sinceDays(days, today)})`},
        ]
        if (only && deleteOlder) parts.push({text: ', and delete them once they are older'})
        return parts
    }
    if (filter.startingFrom) {
        return [{text: `${lead}episodes published since `}, {text: shortDate(new Date(`${filter.startingFrom}T00:00:00`)), strong: true}]
    }
    return [{text: `${lead}episodes published …`}]
}

/**
 * "Skip if the title contains the word “trailer”", with the regex itself at the end.
 * A date line also says whether it deletes, which the profile decides with deleteOlder.
 */
export function filterSentence(
    filter: FilterLike,
    typeLabel: (key: string) => string = (key) => key,
    seasonLabel: (slug: string) => string = (slug) => slug,
    deleteOlder = false,
    today: Date = new Date(),
): Part[] {
    if (isDateLine(filter)) return dateLineSentence(filter, deleteOlder, today)
    const lead = {text: `${ACTION_WORDS[filter.action] ?? ACTION_WORDS.skip} `}
    if (filter.field === 'types' || filter.field === 'seasons') {
        const labels = filter.field === 'types'
            ? (filter.episodeTypes ?? []).map(typeLabel)
            : [...(filter.seasonSlugs ?? []).map(seasonLabel), ...(filter.includeUpcoming ? ['upcoming seasons'] : [])]
        const parts: Part[] = [lead, {text: filter.field === 'types' ? 'episode type' : 'season', strong: true}]
        if (!labels.length) return [...parts, {text: ' is …'}]
        return [...parts, {text: ' is '}, ...strongList(labels).flatMap((part) => (
            part.text === ' and ' ? [{text: ' or '}] : [part]
        ))]
    }
    const parts: Part[] = [lead, {text: filter.field, strong: true}]
    if (filter.field === 'duration') {
        const operator = filter.durationOperator === 'longer' ? ' is longer than ' : ' is shorter than '
        parts.push({text: operator}, {text: filter.durationSeconds ? formatDuration(filter.durationSeconds) : '…', strong: true})
        return parts
    }
    const {pattern, ignoreCase} = splitIgnoreCase(filter.pattern)
    if (!pattern) {
        parts.push({text: ' matches …'})
        return parts
    }
    const described = describeMatch(pattern)
    parts.push({text: ` ${described ?? 'matches'}`})
    if (ignoreCase && described) parts.push({text: ', in any capitalisation'})
    parts.push({text: pattern, code: true})
    return parts
}

export function plainText(parts: Part[]): string {
    return parts.filter((part) => !part.code).map((part) => part.text).join('').trim()
}

/** "Video and Livestream" */
export function joinAnd(items: string[]): string {
    if (items.length <= 1) return items.join('')
    return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`
}

function strongList(items: string[]): Part[] {
    const parts: Part[] = []
    items.forEach((item, index) => {
        if (index > 0) parts.push({text: index === items.length - 1 ? ' and ' : ', '})
        parts.push({text: item, strong: true})
    })
    return parts
}

function shortDate(date: Date): string {
    return date.toLocaleDateString(undefined, {day: 'numeric', month: 'short', year: 'numeric'})
}
