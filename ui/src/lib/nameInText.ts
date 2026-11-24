/** A name as it reads inside a sentence: in quotes when it starts with "for", such as "for KING & COUNTRY", which
 *  would otherwise read as part of the sentence; otherwise as it is. Headings that show the name alone keep it bare. */
export function nameInText(name: string): string {
    return /^for\s/i.test(name) ? `"${name}"` : name
}
