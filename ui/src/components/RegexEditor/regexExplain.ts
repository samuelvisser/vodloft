/**
 * A part-by-part explanation of a regex, and the colours of its parts.
 *
 * The server decides whether a regex is valid and what it matches; this only
 * reads the parts it recognises so people can see what they wrote. Anything it
 * does not recognise is shown as itself.
 */

export type TokenKind = 'literal' | 'escape' | 'class' | 'group' | 'quantifier' | 'anchor' | 'alternation' | 'any'

export type Token = {start: number; end: number; kind: TokenKind}

export type ExplainRow = {source: string; text: string; depth: number}

export type Explanation = {
    rows: ExplainRow[]
    /** Parts the Pattern builder has no block for, such as "not followed by". */
    unsupported: string[]
}

const ESCAPES: Record<string, string> = {
    d: 'a digit',
    D: 'anything but a digit',
    w: 'a letter, digit or underscore',
    W: 'anything but a letter, digit or underscore',
    s: 'a space',
    S: 'anything but a space',
    b: 'a word boundary',
    B: 'not a word boundary',
    t: 'a tab',
    n: 'a new line',
    A: 'the very start',
    Z: 'the very end',
}

const PLURAL: Record<string, string> = {
    'a digit': 'digits',
    'a space': 'spaces',
    'a letter, digit or underscore': 'letters, digits or underscores',
    'any character': 'characters',
}

function plural(text: string): string {
    if (PLURAL[text]) return PLURAL[text]
    return text.replace(/^(a|an|one) /, '').replace(/^the /, '') + (text.startsWith('“') ? '' : '')
}

function quantified(text: string, quantifier: string): string {
    const lazy = quantifier.length > 1 && quantifier.endsWith('?') && !quantifier.startsWith('{') ? ' (as few as possible)' : ''
    const q = lazy ? quantifier.slice(0, -1) : quantifier
    if (q === '?') return `optionally ${text}`
    if (q === '*') return text === 'any character' ? `any text${lazy}` : `any number of ${plural(text)}, or none${lazy}`
    if (q === '+') return text === 'any character' ? `at least one character${lazy}` : `one or more ${plural(text)}${lazy}`
    const range = q.match(/^\{(\d+)(,(\d*))?\}\??$/)
    if (!range) return text
    const [, min, comma, max] = range
    if (!comma) return `exactly ${min} ${Number(min) === 1 ? text.replace(/^(a|an) /, '') : plural(text)}`
    if (max === '') return `at least ${min} ${plural(text)}`
    return `${min} to ${max} ${plural(text)}`
}

function describeClass(body: string): string {
    const negated = body.startsWith('^')
    const inner = negated ? body.slice(1) : body
    const parts: string[] = []
    for (let i = 0; i < inner.length; i += 1) {
        let char = inner[i]
        if (char === '\\' && i + 1 < inner.length) {
            const next = inner[i + 1]
            i += 1
            if (ESCAPES[next]) {
                parts.push(ESCAPES[next].replace(/^(a|an) /, ''))
                continue
            }
            char = next
        }
        if (inner[i + 1] === '-' && i + 2 < inner.length) {
            parts.push(`${char} to ${inner[i + 2]}`)
            i += 2
            continue
        }
        parts.push(`“${char}”`)
    }
    const list = parts.length > 1 ? `${parts.slice(0, -1).join(', ')} or ${parts[parts.length - 1]}` : parts[0] ?? 'nothing'
    return negated ? `any character except ${list}` : `one of ${list}`
}

const GROUPS: Array<[string, string, string | null]> = [
    ['(?:', 'A group of', null],
    ['(?=', 'Only if what follows is', 'followed by'],
    ['(?!', 'Only if what follows is not', 'not followed by'],
    ['(?<=', 'Only if what comes before is', 'preceded by'],
    ['(?<!', 'Only if what comes before is not', 'not preceded by'],
]

type Parsed = {tokens: Token[]; rows: ExplainRow[]; unsupported: Set<string>}

/** Reads one alternative after another until the closing parenthesis of a group, or the end. */
function parseSequence(src: string, start: number, depth: number, out: Parsed): number {
    let i = start
    let literal = ''
    let literalStart = i

    const flushLiteral = () => {
        if (literal) {
            out.rows.push({source: src.slice(literalStart, i), text: `The text “${literal}”`, depth})
            literal = ''
        }
    }

    const quantifierAt = (position: number): string => {
        const found = src.slice(position).match(/^(?:[*+?]|\{\d+(?:,\d*)?\})\??/)
        return found ? found[0] : ''
    }

    const push = (from: number, to: number, kind: TokenKind, text: string) => {
        flushLiteral()
        out.tokens.push({start: from, end: to, kind})
        const quantifier = quantifierAt(to)
        if (quantifier) {
            out.tokens.push({start: to, end: to + quantifier.length, kind: 'quantifier'})
            text = quantified(text, quantifier)
            to += quantifier.length
        }
        out.rows.push({source: src.slice(from, to), text: text[0].toUpperCase() + text.slice(1), depth})
        return to
    }

    while (i < src.length) {
        const char = src[i]
        if (char === ')') break
        if (char === '|') {
            flushLiteral()
            out.tokens.push({start: i, end: i + 1, kind: 'alternation'})
            out.rows.push({source: '|', text: 'Or', depth})
            i += 1
            literalStart = i
            continue
        }
        if (char === '^' || char === '$') {
            i = push(i, i + 1, 'anchor', char === '^' ? 'the start' : 'the end')
            literalStart = i
            continue
        }
        if (char === '.') {
            i = push(i, i + 1, 'any', 'any character')
            literalStart = i
            continue
        }
        if (char === '[') {
            const close = (() => {
                let j = i + 1
                if (src[j] === '^') j += 1
                if (src[j] === ']') j += 1
                for (; j < src.length; j += 1) {
                    if (src[j] === '\\') j += 1
                    else if (src[j] === ']') return j
                }
                return -1
            })()
            if (close < 0) {
                out.rows.push({source: src.slice(i), text: 'An unclosed [', depth})
                return src.length
            }
            i = push(i, close + 1, 'class', describeClass(src.slice(i + 1, close)))
            literalStart = i
            continue
        }
        if (char === '\\' && i + 1 < src.length) {
            const next = src[i + 1]
            if (ESCAPES[next]) {
                const isAnchor = 'bBAZ'.includes(next)
                i = push(i, i + 2, isAnchor ? 'anchor' : 'escape', ESCAPES[next])
                literalStart = i
                continue
            }
            // An escaped character means itself; it joins the text around it unless a quantifier follows.
            if (quantifierAt(i + 2)) {
                i = push(i, i + 2, 'literal', `“${next}”`)
                literalStart = i
                continue
            }
            if (!literal) literalStart = i
            out.tokens.push({start: i, end: i + 2, kind: 'escape'})
            literal += next
            i += 2
            continue
        }
        if (char === '(') {
            flushLiteral()
            const group = GROUPS.find(([open]) => src.startsWith(open, i))
            const named = src.slice(i).match(/^\(\?P?<([A-Za-z_]\w*)>/)
            const open = group?.[0] ?? (named ? named[0] : src.startsWith('(?', i) ? null : '(')
            if (open === null) {
                out.unsupported.add('inline flags')
                out.rows.push({source: src.slice(i), text: 'A part VODLoft cannot explain', depth})
                return src.length
            }
            const title = group?.[1] ?? (named ? `A group named “${named[1]}” of` : 'A group of')
            const unsupported = group?.[2] ?? 'capture groups'
            out.unsupported.add(group && !group[2] ? '' : unsupported)
            out.tokens.push({start: i, end: i + open.length, kind: 'group'})
            const rowIndex = out.rows.length
            out.rows.push({source: `${open} … )`, text: `${title}:`, depth})
            const end = parseSequence(src, i + open.length, depth + 1, out)
            if (src[end] !== ')') {
                out.rows[rowIndex].text = 'An unclosed group'
                return src.length
            }
            out.tokens.push({start: end, end: end + 1, kind: 'group'})
            i = end + 1
            const quantifier = quantifierAt(i)
            if (quantifier) {
                out.tokens.push({start: i, end: i + quantifier.length, kind: 'quantifier'})
                out.rows[rowIndex].text = `${quantified('the group', quantifier).replace(/^./, (c) => c.toUpperCase())}:`
                out.rows[rowIndex].source += quantifier
                i += quantifier.length
            }
            literalStart = i
            continue
        }
        const quantifier = quantifierAt(i + 1)
        if (quantifier && literal) {
            // The quantifier applies to this last character only.
            flushLiteral()
        }
        if (quantifier) {
            i = push(i, i + 1, 'literal', `“${char}”`)
            literalStart = i
            continue
        }
        if (!literal) literalStart = i
        out.tokens.push({start: i, end: i + 1, kind: 'literal'})
        literal += char
        i += 1
    }
    flushLiteral()
    return i
}

function parse(pattern: string): Parsed {
    const out: Parsed = {tokens: [], rows: [], unsupported: new Set()}
    let i = 0
    while (i < pattern.length) {
        i = parseSequence(pattern, i, 0, out)
        if (pattern[i] === ')') {
            out.rows.push({source: ')', text: 'A ) without its (', depth: 0})
            i += 1
        }
    }
    out.unsupported.delete('')
    return out
}

export function explainRegex(pattern: string): Explanation {
    const parsed = parse(pattern)
    return {rows: parsed.rows, unsupported: [...parsed.unsupported]}
}

export function regexTokens(pattern: string): Token[] {
    return parse(pattern).tokens
}
