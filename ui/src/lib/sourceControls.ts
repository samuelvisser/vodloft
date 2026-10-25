import {hasSourceFeature, SourceFeature} from '../types/schemas/source'

type SourcedItem = {sourceFeatures?: readonly string[] | null} | null | undefined

/**
 * Which Source-specific controls to show for an item. Each is only shown when the
 * item's Source has the Feature behind it. ``undefined`` means the item is not
 * saved yet; it is being added from The Daily Wire, so it keeps every control.
 */
export function sourceControls(item: SourcedItem) {
    const has = (feature: Parameters<typeof hasSourceFeature>[1]) => item === undefined || hasSourceFeature(item, feature)
    return {
        membershipLevels: has(SourceFeature.MEMBERSHIP_LEVELS),
        liveEpisodes: has(SourceFeature.LIVE_EPISODES),
        countdownDownloads: has(SourceFeature.LIVE_EPISODES),
        rssStreaming: has(SourceFeature.RSS_STREAMING),
        movieExtras: has(SourceFeature.MOVIE_EXTRAS),
        // Listed episodes are not refreshed from their Source after they are indexed.
        metadataRefresh: item === undefined || !hasSourceFeature(item, SourceFeature.EPISODE_LISTS),
    }
}

export type ResolvedLinkLike = {
    source: {id: string}
    kind: 'show' | 'movie' | 'episode' | 'video'
    slug: string
    url: string
    showSlug?: string | null
    showUrl?: string | null
    preview: {title: string}
}

/** What a link hands off to: a show to add or open, a movie page, or a single video to add. */
export type MediaLinkTarget = {
    kind: 'show' | 'movie' | 'video'
    sourceKey: string
    slug: string
    url: string
    title: string
}

/** The show, movie or video a resolved link should open. An episode opens its show. */
export function linkTarget(link: ResolvedLinkLike): MediaLinkTarget | null {
    const base = {sourceKey: link.source.id, title: link.preview.title}
    if (link.kind === 'movie') return {...base, kind: 'movie', slug: link.slug, url: link.url}
    if (link.kind === 'show') return {...base, kind: 'show', slug: link.slug, url: link.url}
    if (link.kind === 'video') return {...base, kind: 'video', slug: link.slug, url: link.url}
    if (link.showSlug && link.showUrl) return {...base, kind: 'show', slug: link.showSlug, url: link.showUrl}
    return null
}
