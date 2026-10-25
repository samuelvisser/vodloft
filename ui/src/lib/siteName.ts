/** The site a link points to, such as ``youtube.com``, for Sources that serve many sites. */
export function siteName(url: string): string | null {
    try {
        return new URL(url).hostname.replace(/^www\./, '')
    } catch {
        return null
    }
}
