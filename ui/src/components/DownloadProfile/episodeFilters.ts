/**
 * What Which episodes knows about one filter, apart from how it reads: where a new
 * filter goes in the list and which episode types a list of filters downloads.
 */

export type FilterLike = {
    action: string
    field: string
    pattern?: string | null
    durationOperator?: string | null
    durationSeconds?: number | null
    episodeTypes?: string[] | null
    seasonSlugs?: string[] | null
    includeUpcoming?: boolean
    days?: number | null
    count?: number | null
    startingFrom?: string | null
}

export const DATE_FIELDS: readonly string[] = ['published', 'downloaded']

export function isDateLine(filter: {field: string}): boolean {
    return DATE_FIELDS.includes(filter.field)
}

const IGNORE_CASE = '(?i)'

/** A pattern as the regex editor shows it: a leading (?i) becomes "any capitalisation". */
export function splitIgnoreCase(pattern: string | null | undefined): {pattern: string; ignoreCase: boolean} {
    const value = pattern ?? ''
    return value.startsWith(IGNORE_CASE)
        ? {pattern: value.slice(IGNORE_CASE.length), ignoreCase: true}
        : {pattern: value, ignoreCase: false}
}

export function joinIgnoreCase(value: {pattern: string; ignoreCase: boolean}): string {
    return value.ignoreCase ? `${IGNORE_CASE}${value.pattern}` : value.pattern
}

/** Seasons go first, episode types below them, date lines last and every other filter just above the date lines. */
function placementRank(field: string): number {
    if (field === 'seasons') return 0
    if (field === 'types') return 1
    if (DATE_FIELDS.includes(field)) return 3
    return 2
}

/** Where a new filter of this field goes in the list. */
export function insertIndex(filters: readonly {field: string}[], field: string): number {
    const rank = placementRank(field)
    const index = filters.findIndex((filter) => placementRank(filter.field) > rank)
    return index === -1 ? filters.length : index
}

/** The episode types these filters download; null when they don't look at episode types. */
export function downloadedEpisodeTypes(filters: readonly FilterLike[], allTypes: readonly string[] = []): string[] | null {
    let types: string[] | null = null
    for (const filter of filters) {
        if (filter.field !== 'types' || !filter.episodeTypes?.length) continue
        if (filter.action === 'only') {
            types = (types ?? filter.episodeTypes).filter((type) => filter.episodeTypes!.includes(type))
        } else if (filter.action === 'skip') {
            types = (types ?? [...allTypes]).filter((type) => !filter.episodeTypes!.includes(type))
        }
    }
    return types
}
