/** A piece of text, or a web address found in it. */
export type TextPart = {kind: 'text', text: string} | {kind: 'link', url: string}

// A web address runs until whitespace or a character that cannot be part of one.
const ADDRESS = /https?:\/\/[^\s<>"'`]+/gi
// Punctuation that usually ends the sentence around an address rather than the address itself.
const TRAILING = /[.,;:!?*'"]+$/
const CLOSERS: Record<string, string> = {')': '(', ']': '[', '}': '{'}

/** Drops punctuation and unmatched closing brackets that end the sentence around an address. */
function trimAddress(address: string): string {
    let url = address
    for (;;) {
        const trimmed = url.replace(TRAILING, '')
        const last = trimmed.slice(-1)
        const opener = last ? CLOSERS[last] : undefined
        if (opener && trimmed.split(last!).length > trimmed.split(opener).length) {
            url = trimmed.slice(0, -1)
            continue
        }
        if (trimmed === url) return url
        url = trimmed
    }
}

/** Splits text such as a description into plain text and the web addresses in it. */
export function splitTextLinks(text: string): TextPart[] {
    const parts: TextPart[] = []
    let start = 0
    for (const match of text.matchAll(ADDRESS)) {
        const url = trimAddress(match[0])
        if (!/^https?:\/\/[^/?#]/i.test(url)) continue
        if (match.index > start) parts.push({kind: 'text', text: text.slice(start, match.index)})
        parts.push({kind: 'link', url})
        start = match.index + url.length
    }
    if (start < text.length) parts.push({kind: 'text', text: text.slice(start)})
    return parts
}
