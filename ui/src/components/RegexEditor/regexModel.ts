/**
 * The regex editor's model: Pattern blocks, the regex they make, and reading a
 * regex back into blocks.
 *
 * What is stored is only the regex and an Ignore case flag. The preset and the
 * blocks are worked out again from the regex every time, like the Cron
 * editor's inferMode(), so the tabs never hold anything the regex does not say.
 * A regex is shown as blocks only when building those blocks gives the same
 * regex back; anything else stays Custom regex.
 *
 * Generated regexes stay readable: a plain space rather than "\ ", and only
 * characters that mean something in a regex are escaped.
 */

export type Position = 'start' | 'end'
export type SpacesMode = 'one' | 'optional' | 'several'
export type DateFormat = 'iso' | 'dmy-dot' | 'dmy-dash' | 'dmy-slash' | 'compact'

export type TextBlock = {kind: 'text'; text: string; wholeWords: boolean}
export type OneOfBlock = {kind: 'oneOf'; items: string[]; wholeWords: boolean}
export type NumberBlock = {kind: 'number'; min: number; max: number | null; optional: boolean}
export type AnyTextBlock = {kind: 'anyText'; max: number | null}
export type SpacesBlock = {kind: 'spaces'; mode: SpacesMode}
export type DateBlock = {kind: 'date'; format: DateFormat}
export type OptionalBlock = {kind: 'optional'; blocks: Block[]}
export type PositionBlock = {kind: 'position'; at: Position}

export type Block =
    | TextBlock
    | OneOfBlock
    | NumberBlock
    | AnyTextBlock
    | SpacesBlock
    | DateBlock
    | OptionalBlock
    | PositionBlock

export type BlockKind = Block['kind']
export type Preset = 'contains' | 'anyOf' | 'pattern' | 'custom'
export type Where = 'anywhere' | 'start' | 'end' | 'whole'

export type RegexValue = {pattern: string; ignoreCase: boolean}

export const DATE_FORMATS: Record<DateFormat, {label: string; example: string; regex: string}> = {
    iso: {label: 'Year-month-day', example: '2026-10-28', regex: '\\d{4}-\\d{2}-\\d{2}'},
    'dmy-dot': {label: 'Day.month.year', example: '28.10.2026', regex: '\\d{1,2}\\.\\d{1,2}\\.\\d{4}'},
    'dmy-dash': {label: 'Day-month-year', example: '28-10-2026', regex: '\\d{1,2}-\\d{1,2}-\\d{4}'},
    'dmy-slash': {label: 'Day/month/year', example: '28/10/2026', regex: '\\d{1,2}/\\d{1,2}/\\d{4}'},
    compact: {label: 'Year month day, no separators', example: '20261028', regex: '\\d{8}'},
}

const DATE_KEYS = Object.keys(DATE_FORMATS) as DateFormat[]

// Characters with a meaning in a regex outside a character class.
const SPECIAL = new Set(['\\', '^', '$', '.', '|', '?', '*', '+', '(', ')', '[', ']', '{', '}'])
// Escapes of characters that need none; a pasted regex may have them, as Python's re.escape writes them.
const NEEDLESS_ESCAPES = new Set([' ', '-', '#', ':', "'", '"', '!', ',', '&', '~', '%', '@', '=', '<', '>', '/', ';', '_'])
const WORD_CHAR = /[\p{L}\p{N}_]/u

export function escapeText(text: string): string {
    return [...text].map((char) => (SPECIAL.has(char) ? `\\${char}` : char)).join('')
}

function boundary(text: string, side: 'start' | 'end'): string {
    const char = side === 'start' ? text[0] : text[text.length - 1]
    return char !== undefined && WORD_CHAR.test(char) ? '\\b' : ''
}

function wrapWords(body: string, first: string, last: string, wholeWords: boolean): string {
    if (!wholeWords) return body
    return `${boundary(first, 'start')}${body}${boundary(last, 'end')}`
}

function numberRegex(block: NumberBlock): string {
    const {min, max, optional} = block
    let core: string
    if (max === null) core = min <= 1 ? '\\d+' : `\\d{${min},}`
    else if (max === min) core = min === 1 ? '\\d' : `\\d{${min}}`
    else core = `\\d{${min},${max}}`
    if (!optional) return core
    if (core === '\\d+') return '\\d*'
    if (core === '\\d') return '\\d?'
    return `(?:${core})?`
}

export function blockRegex(block: Block): string {
    switch (block.kind) {
        case 'text':
            return wrapWords(escapeText(block.text), block.text, block.text, block.wholeWords)
        case 'oneOf': {
            const items = block.items.filter((item) => item !== '')
            if (!items.length) return ''
            const body = `(?:${items.map(escapeText).join('|')})`
            if (!block.wholeWords) return body
            // A boundary only fits where every item starts (or ends) with a letter or digit.
            const start = items.every((item) => boundary(item, 'start')) ? '\\b' : ''
            const end = items.every((item) => boundary(item, 'end')) ? '\\b' : ''
            return `${start}${body}${end}`
        }
        case 'number':
            return numberRegex(block)
        case 'anyText':
            return block.max === null ? '.*' : `.{0,${block.max}}`
        case 'spaces':
            return {one: '\\s', optional: '\\s*', several: '\\s+'}[block.mode]
        case 'date':
            return DATE_FORMATS[block.format].regex
        case 'optional': {
            const [only] = block.blocks
            if (block.blocks.length === 1 && only.kind === 'oneOf' && !only.wholeWords) return `${blockRegex(only)}?`
            const inner = buildRegex(block.blocks)
            return inner ? `(?:${inner})?` : ''
        }
        case 'position':
            return block.at === 'start' ? '^' : '$'
    }
}

export function buildRegex(blocks: Block[]): string {
    return blocks.map(blockRegex).join('')
}

/** The regex with needless escapes removed, so "livestream\ replay" reads the same as "livestream replay". */
export function canonicalRegex(pattern: string): string {
    let out = ''
    let inClass = false
    for (let i = 0; i < pattern.length; i += 1) {
        const char = pattern[i]
        if (char === '\\' && i + 1 < pattern.length) {
            const next = pattern[i + 1]
            out += !inClass && NEEDLESS_ESCAPES.has(next) ? next : char + next
            i += 1
            continue
        }
        if (char === '[') inClass = true
        else if (char === ']') inClass = false
        out += char
    }
    return out
}

// Reading a regex back into blocks -------------------------------------------

class Reader {
    i = 0
    constructor(readonly src: string) {}

    get done() {
        return this.i >= this.src.length
    }

    peek(text: string): boolean {
        return this.src.startsWith(text, this.i)
    }

    take(text: string): boolean {
        if (!this.peek(text)) return false
        this.i += text.length
        return true
    }

    match(re: RegExp): RegExpMatchArray | null {
        const found = this.src.slice(this.i).match(re)
        if (!found || found.index !== 0) return null
        this.i += found[0].length
        return found
    }
}

/** A run of literal characters, escaped specials included. Stops before anything else. */
function readLiteral(reader: Reader, stopAt: string = ''): string {
    let text = ''
    while (!reader.done) {
        const char = reader.src[reader.i]
        if (char === '\\') {
            const next = reader.src[reader.i + 1]
            if (next !== undefined && (SPECIAL.has(next) || NEEDLESS_ESCAPES.has(next))) {
                text += next
                reader.i += 2
                continue
            }
            break
        }
        if (SPECIAL.has(char) || stopAt.includes(char)) break
        text += char
        reader.i += 1
    }
    return text
}

/** "(?:a|b|c)" with literal items, or null. */
function readAlternation(reader: Reader): string[] | null {
    const start = reader.i
    if (!reader.take('(?:')) return null
    const items: string[] = []
    while (true) {
        items.push(readLiteral(reader, '|'))
        if (reader.take('|')) continue
        if (reader.take(')')) break
        reader.i = start
        return null
    }
    if (items.length === 1 && (!items[0] || reader.peek('?'))) {
        // "(?:Ep )?" is an optional group, not a list of one.
        reader.i = start
        return null
    }
    return items
}

function readBlocks(reader: Reader, inGroup: boolean): Block[] | null {
    const blocks: Block[] = []
    while (!reader.done) {
        if (inGroup && reader.peek(')')) break
        const block = readBlock(reader, blocks.length === 0 && !inGroup)
        if (block === null) return null
        blocks.push(block)
    }
    return blocks
}

function readBlock(reader: Reader, atStart: boolean): Block | null {
    const start = reader.i
    if (reader.peek('^')) {
        if (!atStart) return null
        reader.i += 1
        return {kind: 'position', at: 'start'}
    }
    if (reader.peek('$')) {
        reader.i += 1
        return reader.done ? {kind: 'position', at: 'end'} : null
    }
    for (const format of DATE_KEYS) {
        if (reader.take(DATE_FORMATS[format].regex)) return {kind: 'date', format}
    }
    let found = reader.match(/^\(\?:\\d(\{\d+(?:,\d*)?\}|\+)?\)\?/)
    if (found) return numberFrom(found[1] ?? '', true)
    found = reader.match(/^\\d(\{\d+(?:,\d*)?\}|[+*?])?/)
    if (found) {
        const quantifier = found[1] ?? ''
        if (quantifier === '*') return {kind: 'number', min: 1, max: null, optional: true}
        if (quantifier === '?') return {kind: 'number', min: 1, max: 1, optional: true}
        return numberFrom(quantifier, false)
    }
    found = reader.match(/^\.(\*|\{0,(\d+)\})/)
    if (found) return {kind: 'anyText', max: found[2] === undefined ? null : Number(found[2])}
    found = reader.match(/^\\s([*+])?/)
    if (found) return {kind: 'spaces', mode: found[1] === '*' ? 'optional' : found[1] === '+' ? 'several' : 'one'}

    const leadingBoundary = reader.take('\\b')
    const items = readAlternation(reader)
    if (items !== null) {
        const wholeWords = leadingBoundary || reader.peek('\\b')
        if (reader.peek('\\b')) reader.i += 2
        if (reader.peek('?') && !wholeWords) {
            reader.i += 1
            return {kind: 'optional', blocks: [{kind: 'oneOf', items, wholeWords: false}]}
        }
        return {kind: 'oneOf', items, wholeWords}
    }
    if (!leadingBoundary && reader.peek('(?:')) {
        reader.i += 3
        const inner = readBlocks(reader, true)
        if (inner === null || !reader.take(')?')) {
            reader.i = start
            return null
        }
        return {kind: 'optional', blocks: inner}
    }
    const text = readLiteral(reader)
    if (!text) {
        reader.i = start
        return null
    }
    // A quantifier right after a literal applies to its last character only; that is not a Text block.
    if (!reader.done && '?*+{'.includes(reader.src[reader.i])) {
        reader.i = start
        return null
    }
    const trailingBoundary = reader.take('\\b')
    return {kind: 'text', text, wholeWords: leadingBoundary || trailingBoundary}
}

function numberFrom(quantifier: string, optional: boolean): NumberBlock {
    if (quantifier === '') return {kind: 'number', min: 1, max: 1, optional}
    if (quantifier === '+') return {kind: 'number', min: 1, max: null, optional}
    const [min, max] = quantifier.slice(1, -1).split(',')
    if (max === undefined) return {kind: 'number', min: Number(min), max: Number(min), optional}
    return {kind: 'number', min: Number(min), max: max === '' ? null : Number(max), optional}
}

/** The blocks a regex is made of, or null when it can only be shown as Custom regex. */
export function parseBlocks(pattern: string): Block[] | null {
    if (pattern === '') return []
    const canonical = canonicalRegex(pattern)
    const reader = new Reader(canonical)
    const blocks = readBlocks(reader, false)
    if (blocks === null || !reader.done) return null
    return buildRegex(blocks) === canonical ? blocks : null
}

// Presets -----------------------------------------------------------------------

export type Shortcut = {where: Where; block: TextBlock | OneOfBlock}

/** Contains and Any of these are one Text or One of block, with Where as Position blocks around it. */
export function shortcutOf(blocks: Block[]): Shortcut | null {
    const inner = [...blocks]
    const start = inner[0]?.kind === 'position' && inner[0].at === 'start'
    if (start) inner.shift()
    const last = inner[inner.length - 1]
    const end = last?.kind === 'position' && last.at === 'end'
    if (end) inner.pop()
    if (inner.length !== 1) return null
    const [block] = inner
    if (block.kind !== 'text' && block.kind !== 'oneOf') return null
    const where: Where = start && end ? 'whole' : start ? 'start' : end ? 'end' : 'anywhere'
    return {where, block}
}

export function shortcutBlocks(where: Where, block: TextBlock | OneOfBlock): Block[] {
    return [
        ...(where === 'start' || where === 'whole' ? [{kind: 'position', at: 'start'} as Block] : []),
        block,
        ...(where === 'end' || where === 'whole' ? [{kind: 'position', at: 'end'} as Block] : []),
    ]
}

export function inferPreset(pattern: string): Preset {
    const blocks = parseBlocks(pattern)
    if (blocks === null) return 'custom'
    if (blocks.length === 0) return 'contains'
    const shortcut = shortcutOf(blocks)
    if (shortcut?.block.kind === 'text') return 'contains'
    if (shortcut?.block.kind === 'oneOf') return 'anyOf'
    return 'pattern'
}

const BLOCK_NAMES: Record<BlockKind, string> = {
    text: 'Text',
    oneOf: 'One of',
    number: 'Number',
    anyText: 'Any text',
    spaces: 'Spaces',
    date: 'Date',
    optional: 'Optional group',
    position: 'Position',
}

export function blockName(kind: BlockKind): string {
    return BLOCK_NAMES[kind]
}

/** Why a tab cannot show this regex, or null when it can. */
export function presetUnavailable(preset: Preset, pattern: string): string | null {
    if (preset === 'custom') return null
    const blocks = parseBlocks(pattern)
    if (blocks === null) return 'Has parts no block can show'
    if (preset === 'pattern' || blocks.length === 0) return null
    const shortcut = shortcutOf(blocks)
    if (shortcut === null) {
        const odd = blocks.find((block) => block.kind !== 'position' && block.kind !== 'text' && block.kind !== 'oneOf')
        return odd ? `Uses a ${blockName(odd.kind)} block` : 'Uses more than one block'
    }
    if (preset === 'contains' && shortcut.block.kind === 'oneOf' && shortcut.block.items.length > 1) {
        return 'Has more than one word or phrase'
    }
    return null
}

/** The regex for a tab when switching to it, keeping what the current regex says. */
export function switchPreset(preset: Preset, pattern: string): string {
    const blocks = parseBlocks(pattern)
    if (preset === 'custom' || preset === 'pattern' || blocks === null) return pattern
    const shortcut = shortcutOf(blocks)
    const where = shortcut?.where ?? 'anywhere'
    const block = shortcut?.block
    if (preset === 'contains') {
        const text = block?.kind === 'text' ? block.text : block?.kind === 'oneOf' ? (block.items[0] ?? '') : ''
        return buildRegex(shortcutBlocks(where, {kind: 'text', text, wholeWords: block?.wholeWords ?? true}))
    }
    const items = block?.kind === 'oneOf' ? block.items : block?.kind === 'text' && block.text ? [block.text] : []
    return buildRegex(shortcutBlocks(where, {kind: 'oneOf', items, wholeWords: block?.wholeWords ?? true}))
}

export function newBlock(kind: BlockKind): Block {
    switch (kind) {
        case 'text':
            return {kind, text: '', wholeWords: false}
        case 'oneOf':
            return {kind, items: [], wholeWords: false}
        case 'number':
            return {kind, min: 1, max: null, optional: false}
        case 'anyText':
            return {kind, max: null}
        case 'spaces':
            return {kind, mode: 'optional'}
        case 'date':
            return {kind, format: 'iso'}
        case 'optional':
            return {kind, blocks: [{kind: 'text', text: '', wholeWords: false}]}
        case 'position':
            return {kind, at: 'start'}
    }
}

// Plain-language descriptions ------------------------------------------------------

function quoteList(items: string[]): string {
    const quoted = items.map((item) => `“${item}”`)
    if (quoted.length <= 1) return quoted.join('')
    return `${quoted.slice(0, -1).join(', ')} or ${quoted[quoted.length - 1]}`
}

export function blockSummary(block: Block): string {
    switch (block.kind) {
        case 'text':
            return block.text || 'empty'
        case 'oneOf':
            return block.items.length ? block.items.join(' | ') : 'empty'
        case 'number':
            if (block.max === null) return `${block.min <= 1 ? 'Any' : `${block.min}+`} digits${block.optional ? ', optional' : ''}`
            if (block.max === block.min) return `${block.min} digit${block.min === 1 ? '' : 's'}${block.optional ? ', optional' : ''}`
            return `${block.min} to ${block.max} digits${block.optional ? ', optional' : ''}`
        case 'anyText':
            return block.max === null ? 'Anything' : `Up to ${block.max} characters`
        case 'spaces':
            return {one: 'One', optional: 'Optional', several: 'One or more'}[block.mode]
        case 'date':
            return DATE_FORMATS[block.format].example
        case 'optional':
            return `${block.blocks.length} block${block.blocks.length === 1 ? '' : 's'}`
        case 'position':
            return block.at === 'start' ? 'Start' : 'End'
    }
}

function describeBlock(block: Block): string {
    switch (block.kind) {
        case 'text':
            return block.wholeWords ? `the word ${quoteList([block.text])}` : quoteList([block.text])
        case 'oneOf':
            return block.wholeWords ? `the word ${quoteList(block.items)}` : `one of ${quoteList(block.items)}`
        case 'number': {
            const size = block.max === null
                ? (block.min <= 1 ? 'a number' : `a number of at least ${block.min} digits`)
                : block.max === block.min ? `a number of ${block.min} digit${block.min === 1 ? '' : 's'}` : `a number of ${block.min} to ${block.max} digits`
            return block.optional ? `optionally ${size}` : size
        }
        case 'anyText':
            return block.max === null ? 'any text' : `up to ${block.max} characters of any text`
        case 'spaces':
            return {one: 'one space', optional: 'optional spaces', several: 'one or more spaces'}[block.mode]
        case 'date':
            return `a date like ${DATE_FORMATS[block.format].example}`
        case 'optional':
            return `optionally ${block.blocks.map(describeBlock).join(', then ')}`
        case 'position':
            return ''
    }
}

/** What texts the blocks match, as a plural verb ("contain") and its object; null when there is nothing to say. */
function verbAndWhat(blocks: Block[]): [string, string] | null {
    if (!blocks.length) return null
    const shortcut = shortcutOf(blocks)
    if (shortcut) {
        const {where, block} = shortcut
        const empty = block.kind === 'text' ? !block.text : !block.items.length
        if (empty) return null
        const verb = {anywhere: 'contain', start: 'start with', end: 'end with', whole: 'are exactly'}[where]
        return [verb, describeBlock(block)]
    }
    const inner = blocks.filter((block) => block.kind !== 'position')
    const starts = blocks[0]?.kind === 'position'
    const ends = blocks[blocks.length - 1]?.kind === 'position' && blocks.length > 1
    const parts = inner.map(describeBlock).filter(Boolean)
    const verb = starts && ends ? 'are exactly' : starts ? 'start with' : 'contain'
    return [verb, `${parts.join(', then ')}${ends && !starts ? ' at the end' : ''}`]
}

/** One sentence that says what the regex matches, when it is made of blocks. */
export function describeBlocks(blocks: Block[], ignoreCase: boolean, noun: string = 'title'): string | null {
    const plural = `${noun[0].toUpperCase()}${noun.slice(1)}s`
    const caseNote = ignoreCase ? ', in any capitalisation' : ', with the capitals exactly as typed'
    const described = verbAndWhat(blocks)
    return described ? `${plural} that ${described[0]} ${described[1]}${caseNote}.` : null
}

const SINGULAR_VERBS: Record<string, string> = {
    contain: 'contains',
    'start with': 'starts with',
    'end with': 'ends with',
    'are exactly': 'is exactly',
}

/** What one text must do to match, such as "contains the word “trailer”"; null when no block can show the regex. */
export function describeMatch(pattern: string): string | null {
    const blocks = parseBlocks(pattern)
    const described = blocks ? verbAndWhat(blocks) : null
    return described ? `${SINGULAR_VERBS[described[0]]} ${described[1]}` : null
}
