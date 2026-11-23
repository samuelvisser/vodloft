/** VODLoft's own template functions, for the help below the editor and its completion menu. */
export type TemplateFunctionArgument = {
    name: string
    description: string
}

export type TemplateFunction = {
    name: string
    /** How a template calls it, with each argument's default. */
    usage: string
    /** One line, also shown in the editor's completion menu. */
    summary: string
    arguments: TemplateFunctionArgument[]
    example?: {code: string, result: string}
    /** Only Collection profiles can use it. */
    collectionOnly?: boolean
}

export const TEMPLATE_FUNCTIONS: readonly TemplateFunction[] = [
    {
        name: 'custom_index',
        usage: "'key' | custom_index(per=None, start=1, step=1)",
        summary: 'This episode\'s number from one of your Indexing values. per counts separately for each value, '
            + 'start and step set the first number and how it changes.',
        arguments: [
            {
                name: "'key'",
                description: 'The key of an Indexing value you added with the Indexing values button, in quotes, '
                    + 'before the |. Episodes are counted in the collection\'s episode order, the same order as '
                    + 'episode_index, and an episode only gets a number when the template reaches it.',
            },
            {
                name: 'per',
                description: 'Counts separately for each value of what you give it. Without per, every episode in '
                    + 'the collection shares one counter. per=date numbers the episodes of each day 1, 2, 3 and '
                    + 'starts again at 1 the next day. per=season_number starts again in each season. A list, such '
                    + 'as per=[year, season_number], counts each combination on its own.',
            },
            {name: 'start', description: 'The first number of each counter. Default 1.'},
            {
                name: 'step',
                description: 'How much each next number changes. Default 1. A negative step counts down: '
                    + 'start=99, step=-1 gives 99, 98, 97. It cannot be 0.',
            },
        ],
        example: {code: "{{ '%02d' | format('day' | custom_index(per=date)) }}", result: '01, then 02 for a second episode that day'},
        collectionOnly: true,
    },
    {
        name: 'strftime',
        usage: 'strftime(format)',
        summary: 'Format a date or time variable, such as date, datetime or time, with Python strftime codes.',
        arguments: [
            {
                name: 'format',
                description: 'The pattern, with codes such as %Y (year), %m (month), %d (day), %B (month name), '
                    + '%a (short day name) and %H:%M (hours and minutes). An unknown date gives an empty value.',
            },
        ],
        example: {code: "{{ date | strftime('%d %B %Y') }}", result: '05 March 2026'},
    },
    {
        name: 'regex_replace',
        usage: 'regex_replace(pattern, replacement, count=0)',
        summary: 'Replace every part of the value that matches a regular expression.',
        arguments: [
            {name: 'pattern', description: 'A Python regular expression.'},
            {
                name: 'replacement',
                description: 'What replaces each match. \\1, \\2 put back what the pattern\'s groups matched; '
                    + 'an empty text removes the match.',
            },
            {name: 'count', description: 'At most this many matches are replaced, from the start. 0 replaces them all.'},
        ],
        example: {code: "{{ episode_title | regex_replace(' [|-] .*$', '') }}", result: 'the title up to its first " | " or " - "'},
    },
    {
        name: 'regex_search',
        usage: 'regex_search(pattern)',
        summary: 'True when a regular expression matches anywhere in the value, for use in an if.',
        arguments: [{name: 'pattern', description: 'A Python regular expression.'}],
        example: {code: "{% if episode_title | regex_search('(?i)trailer') %}Trailers/{% endif %}", result: 'Trailers/ for trailers'},
    },
    {
        name: 'regex_groups',
        usage: 'regex_groups(pattern)',
        summary: 'The groups of the first match of a regular expression, as a list. Nothing matched gives an empty list.',
        arguments: [
            {
                name: 'pattern',
                description: 'A Python regular expression with groups in brackets. Take one group with [0], [1]; '
                    + 'a group that did not take part in the match is empty.',
            },
        ],
        example: {
            code: "{% set part = episode_title | regex_groups('Part ([0-9]+)') %}{{ part[0] if part }}",
            result: '2 for "Story, Part 2"',
        },
    },
    {
        name: 'as_typed',
        usage: 'as_typed',
        summary: 'Name files with the value as if you typed it into the template: in Restricted mode it keeps its '
            + 'spaces and punctuation. It can still not add a folder. Use it last.',
        arguments: [],
        example: {code: '{{ collection_title | as_typed }}', result: 'My Show, not My_Show'},
    },
]
