/** What an output template can call: VODLoft's own functions and Jinja's filters, for the template reference and the editor's completion menu. */
export type TemplateFunctionArgument = {
    name: string
    /** The value it takes when left out, or "required". */
    default: string
    description: string
}

export type TemplateFunction = {
    name: string
    /** How a template calls it, with each argument's default. */
    usage: string
    /** One line, shown on its folded row. */
    summary: string
    /** What it does, shown when the row opens and in the completion menu. */
    description: string
    arguments: TemplateFunctionArgument[]
    example?: {code: string, result: string}
    /** Only Collection profiles can use it. */
    collectionOnly?: boolean
}

export const TEMPLATE_FUNCTIONS: readonly TemplateFunction[] = [
    {
        name: 'custom_index',
        usage: "'key' | custom_index(per=None, start=1, step=1)",
        summary: 'Number episodes with one of your own Indexing values',
        description: 'This episode\'s number from one of your Indexing values. Episodes are counted in the '
            + 'collection\'s episode order, the same order as episode_index, and an episode only gets a number '
            + 'when the template reaches it.',
        arguments: [
            {
                name: "'key'",
                default: 'required',
                description: 'Which Indexing value to count: its key in quotes, before the |. Add Indexing values '
                    + 'with the Indexing values button.',
            },
            {
                name: 'per',
                default: 'none',
                description: 'Start counting again for each value of what you give it. per=date numbers each '
                    + 'day\'s episodes 1, 2, 3; per=season_number starts again in each season. A list such as '
                    + 'per=[year, season_number] counts each combination. Without per, the whole collection '
                    + 'shares one counter.',
            },
            {name: 'start', default: '1', description: 'The first number of each counter.'},
            {
                name: 'step',
                default: '1',
                description: 'How much each next number changes. A negative step counts down: start=99, step=-1 '
                    + 'gives 99, 98, 97. It cannot be 0.',
            },
        ],
        example: {code: "{{ '%02d' | format('day' | custom_index(per=date)) }}", result: '01, then 02 for a second episode that day'},
        collectionOnly: true,
    },
    {
        name: 'strftime',
        usage: 'strftime(format)',
        summary: 'Write a date or time your own way',
        description: 'Formats a date or time variable, such as date, datetime or time. An unknown date gives an '
            + 'empty value.',
        arguments: [
            {
                name: 'format',
                default: 'required',
                description: 'The pattern, with codes such as %Y (year), %m (month), %d (day), %B (month name), '
                    + '%a (short day name) and %H:%M (hours and minutes).',
            },
        ],
        example: {code: "{{ date | strftime('%d %B %Y') }}", result: '05 March 2026'},
    },
    {
        name: 'regex_replace',
        usage: 'regex_replace(pattern, replacement, count=0)',
        summary: 'Replace or remove part of a value',
        description: 'Replaces every part of the value that matches a regular expression.',
        arguments: [
            {name: 'pattern', default: 'required', description: 'A Python regular expression.'},
            {
                name: 'replacement',
                default: 'required',
                description: 'What replaces each match. \\1, \\2 put back what the pattern\'s groups matched; '
                    + 'an empty text removes the match.',
            },
            {name: 'count', default: '0', description: 'Replace only this many matches, from the start. 0 replaces them all.'},
        ],
        example: {code: "{{ episode_title | regex_replace(' [|-] .*$', '') }}", result: 'the title up to its first " | " or " - "'},
    },
    {
        name: 'regex_search',
        usage: 'regex_search(pattern)',
        summary: 'Check whether a value contains something',
        description: 'True when a regular expression matches anywhere in the value, for use in an if.',
        arguments: [{name: 'pattern', default: 'required', description: 'A Python regular expression.'}],
        example: {code: "{% if episode_title | regex_search('(?i)trailer') %}Trailers/{% endif %}", result: 'Trailers/ for trailers'},
    },
    {
        name: 'regex_groups',
        usage: 'regex_groups(pattern)',
        summary: 'Pick a piece out of a value',
        description: 'The groups of the first match of a regular expression, as a list. Nothing matched gives an '
            + 'empty list.',
        arguments: [
            {
                name: 'pattern',
                default: 'required',
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
        summary: 'Use a variable as if you typed it out',
        description: 'VODLoft uses stricter rules for formatting variables in your path than it does for parts of '
            + 'the path you simply type out. This allows you to process a variable as if you typed it out.',
        arguments: [],
        example: {code: '{{ collection_title | as_typed }}', result: 'My Show in Restricted mode, not My_Show'},
    },
]

export type JinjaFilter = {
    name: string
    usage: string
    description: string
}

/** Jinja's own filters, which output templates can use too. */
export const JINJA_FILTERS: readonly JinjaFilter[] = [
    {name: 'abs', usage: 'abs', description: 'Return the absolute value of a number.'},
    {name: 'attr', usage: 'attr(name)', description: 'Get an attribute from an object.'},
    {name: 'batch', usage: 'batch(linecount, fill_with=None)', description: 'Group items into rows with up to linecount items each.'},
    {name: 'capitalize', usage: 'capitalize', description: 'Capitalize the first character and lowercase the rest.'},
    {name: 'center', usage: 'center(width=80)', description: 'Center text in a field of the given width.'},
    {name: 'count', usage: 'count', description: 'Return the number of items in a value.'},
    {name: 'd', usage: "d(default_value='', boolean=False)", description: 'Alias for the default filter.'},
    {name: 'default', usage: "default(default_value='', boolean=False)", description: 'Use default_value instead of the value. VODLoft gives an unknown value as empty text, so pass boolean=true to replace empty values too.'},
    {name: 'dictsort', usage: "dictsort(case_sensitive=False, by='key', reverse=False)", description: 'Sort a dictionary and return key/value pairs.'},
    {name: 'e', usage: 'e', description: 'Alias for the escape filter.'},
    {name: 'escape', usage: 'escape', description: 'Escape HTML-special characters.'},
    {name: 'filesizeformat', usage: 'filesizeformat(binary=False)', description: 'Format a number as a human-readable file size.'},
    {name: 'first', usage: 'first', description: 'Return the first item in a sequence.'},
    {name: 'float', usage: 'float(default=0.0)', description: 'Convert a value to a floating-point number.'},
    {name: 'forceescape', usage: 'forceescape', description: 'Apply HTML escaping even to values already marked safe.'},
    {name: 'format', usage: 'format(*args, **kwargs)', description: "Fill the value, a printf-style pattern, with the arguments: '%02d' | format(3) gives 03."},
    {name: 'groupby', usage: 'groupby(attribute, default=None, case_sensitive=False)', description: 'Group items by an attribute.'},
    {name: 'indent', usage: 'indent(width=4, first=False, blank=False)', description: 'Indent lines in a string.'},
    {name: 'int', usage: 'int(default=0, base=10)', description: 'Convert a value to a whole number; default when it is not a number, base for another number base such as 16.'},
    {name: 'items', usage: 'items', description: 'Iterate over the key/value pairs in a mapping.'},
    {name: 'join', usage: "join(d='', attribute=None)", description: 'Join items into a string, optionally using an attribute from each item.'},
    {name: 'last', usage: 'last', description: 'Return the last item in a sequence.'},
    {name: 'length', usage: 'length', description: 'Return the number of items in a value.'},
    {name: 'list', usage: 'list', description: 'Convert a value to a list.'},
    {name: 'lower', usage: 'lower', description: 'Convert text to lowercase.'},
    {name: 'map', usage: 'map(*args, **kwargs)', description: 'Transform a sequence by applying a filter or reading an attribute.'},
    {name: 'max', usage: 'max(case_sensitive=False, attribute=None)', description: 'Return the largest item in a sequence.'},
    {name: 'min', usage: 'min(case_sensitive=False, attribute=None)', description: 'Return the smallest item in a sequence.'},
    {name: 'pprint', usage: 'pprint', description: 'Format a value for debugging.'},
    {name: 'random', usage: 'random', description: 'Return a random item from a sequence.'},
    {name: 'reject', usage: 'reject(*args, **kwargs)', description: 'Keep sequence items that fail a Jinja test.'},
    {name: 'rejectattr', usage: 'rejectattr(*args, **kwargs)', description: 'Keep items whose selected attribute fails a Jinja test.'},
    {name: 'replace', usage: 'replace(old, new, count=None)', description: 'Replace the text old with new; count replaces only the first so many.'},
    {name: 'reverse', usage: 'reverse', description: 'Reverse text or iterate over a sequence in reverse.'},
    {name: 'round', usage: "round(precision=0, method='common')", description: 'Round a number to the requested precision.'},
    {name: 'safe', usage: 'safe', description: 'Mark a string as safe from HTML escaping.'},
    {name: 'select', usage: 'select(*args, **kwargs)', description: 'Keep sequence items that pass a Jinja test.'},
    {name: 'selectattr', usage: 'selectattr(*args, **kwargs)', description: 'Keep items whose selected attribute passes a Jinja test.'},
    {name: 'slice', usage: 'slice(slices, fill_with=None)', description: 'Split a sequence into the requested number of slices.'},
    {name: 'sort', usage: 'sort(reverse=False, case_sensitive=False, attribute=None)', description: 'Sort a sequence.'},
    {name: 'string', usage: 'string', description: 'Convert a value to a string.'},
    {name: 'striptags', usage: 'striptags', description: 'Remove SGML or XML tags and normalize adjacent whitespace.'},
    {name: 'sum', usage: 'sum(attribute=None, start=0)', description: 'Add the values in a sequence.'},
    {name: 'title', usage: 'title', description: 'Convert text to title case.'},
    {name: 'tojson', usage: 'tojson(indent=None)', description: 'Serialize a value as JSON.'},
    {name: 'trim', usage: 'trim(chars=None)', description: 'Remove chars, or spaces when you leave it out, from the start and end.'},
    {name: 'truncate', usage: "truncate(length=255, killwords=False, end='...', leeway=None)", description: 'Shorten text to length characters, ending in end; killwords=true may cut a word in half, leeway lets text that is only that much too long stay whole.'},
    {name: 'unique', usage: 'unique(case_sensitive=False, attribute=None)', description: 'Return unique items from a sequence.'},
    {name: 'upper', usage: 'upper', description: 'Convert text to uppercase.'},
    {name: 'urlencode', usage: 'urlencode', description: 'Encode a value for use in a URL path or query.'},
    {name: 'urlize', usage: 'urlize(trim_url_limit=None, nofollow=False, target=None, rel=None, extra_schemes=None)', description: 'Convert URLs in text to HTML links.'},
    {name: 'wordcount', usage: 'wordcount', description: 'Count words in a string.'},
    {name: 'wordwrap', usage: 'wordwrap(width=79, break_long_words=True, wrapstring=None, break_on_hyphens=True)', description: 'Wrap text to the requested width.'},
    {name: 'xmlattr', usage: 'xmlattr(autospace=True)', description: 'Build an SGML/XML attribute string from a mapping.'},
]
