/**
 * The sentences of Which episodes. Each line of the section reads as a part of
 * one sentence, with the values that matter in bold.
 */
import {describeMatch} from '../RegexEditor/regexModel'

/** A piece of a sentence; strong pieces are the values you chose. */
export type Part = {text: string; strong?: boolean; code?: boolean}

const ACTION_WORDS: Record<string, string> = {
    skip: 'Skip if the',
    only: 'Only download if the',
    keep: 'Keep if the',
}

const UNITS: Array<[number, string]> = [[86_400, 'day'], [3_600, 'hour'], [60, 'minute'], [1, 'second']]

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

export type RuleLike = {
    action: string
    field: string
    pattern?: string | null
    ignoreCase?: boolean
    durationOperator?: string | null
    durationSeconds?: number | null
    episodeTypes?: string[] | null
    seasonSlugs?: string[] | null
}

/** Whether a rule says enough to count which episodes it leaves out. */
export function ruleComplete(rule: RuleLike): boolean {
    if (rule.field === 'types') return !!rule.episodeTypes?.length
    if (rule.field === 'seasons') return !!rule.seasonSlugs?.length
    if (rule.field === 'duration') return !!rule.durationSeconds && !!rule.durationOperator
    return !!rule.pattern
}

/** "Skip if the title contains the word “trailer”", with the regex itself at the end. */
export function ruleSentence(
    rule: RuleLike,
    typeLabel: (key: string) => string = (key) => key,
    seasonLabel: (slug: string) => string = (slug) => slug,
): Part[] {
    if (rule.field === 'types' || rule.field === 'seasons') {
        const labels = rule.field === 'types' ? (rule.episodeTypes ?? []).map(typeLabel) : (rule.seasonSlugs ?? []).map(seasonLabel)
        const parts: Part[] = [
            {text: `${ACTION_WORDS[rule.action] ?? ACTION_WORDS.skip} `},
            {text: rule.field === 'types' ? 'episode type' : 'season', strong: true},
        ]
        if (!labels.length) return [...parts, {text: ' is …'}]
        return [...parts, {text: ' is '}, ...strongList(labels).flatMap((part) => (
            part.text === ' and ' ? [{text: ' or '}] : [part]
        ))]
    }
    const parts: Part[] = [{text: `${ACTION_WORDS[rule.action] ?? ACTION_WORDS.skip} `}, {text: rule.field, strong: true}]
    if (rule.field === 'duration') {
        const operator = rule.durationOperator === 'longer' ? ' is longer than ' : ' is shorter than '
        parts.push({text: operator}, {text: rule.durationSeconds ? formatDuration(rule.durationSeconds) : '…', strong: true})
        return parts
    }
    const pattern = rule.pattern ?? ''
    if (!pattern) {
        parts.push({text: ' matches …'})
        return parts
    }
    const described = describeMatch(pattern)
    parts.push({text: ` ${described ?? 'matches'}`})
    if (rule.ignoreCase && described) parts.push({text: ', in any capitalisation'})
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

export function typesSentence(labels: string[]): Part[] {
    if (!labels.length) return [{text: 'Download '}, {text: 'no', strong: true}, {text: ' episode types'}]
    return [{text: 'Download '}, ...strongList(labels), {text: ' episodes'}]
}

export function seasonsSentence(names: string[], includeUpcoming: boolean): Part[] {
    const items = [...names, ...(includeUpcoming ? ['upcoming seasons'] : [])]
    if (!items.length) return [{text: 'from '}, {text: 'no seasons', strong: true}]
    return [{text: 'from '}, ...strongList(items)]
}

export type DateWindow = {
    downloadDaysInPast: number
    downloadEpisodeCount: number
    downloadStartingFrom: string | null
    deleteOlderEpisodes: boolean
    retentionFrom: string
}

function shortDate(date: Date): string {
    return date.toLocaleDateString(undefined, {day: 'numeric', month: 'short', year: 'numeric'})
}

export function dateSentence(window: DateWindow, today: Date = new Date()): Part[] {
    const days = Number.isFinite(window.downloadDaysInPast) ? window.downloadDaysInPast : 0
    const count = Number.isFinite(window.downloadEpisodeCount) ? window.downloadEpisodeCount : 0
    if (count > 0) {
        const parts: Part[] = [{text: 'only the '}, {text: `latest ${count}`, strong: true}, {text: count === 1 ? ' episode' : ' episodes'}]
        if (window.deleteOlderEpisodes) parts.push({text: ', and delete older ones'})
        return parts
    }
    if (days > 0) {
        const since = new Date(today)
        since.setHours(0, 0, 0, 0)
        since.setDate(since.getDate() - days)
        const parts: Part[] = [
            {text: 'published in the '},
            {text: `last ${days} ${days === 1 ? 'day' : 'days'}`, strong: true},
            {text: ` (since ${shortDate(since)})`},
        ]
        if (window.deleteOlderEpisodes) {
            parts.push(window.retentionFrom === 'downloaded'
                ? {text: `, and delete them ${days} ${days === 1 ? 'day' : 'days'} after downloading`}
                : {text: ', and delete them once they are older'})
        }
        return parts
    }
    if (window.downloadStartingFrom) {
        return [{text: 'published since '}, {text: shortDate(new Date(`${window.downloadStartingFrom}T00:00:00`)), strong: true}]
    }
    return [{text: 'published at '}, {text: 'any time', strong: true}]
}
