import DownloadStatusBadge from '../DownloadProgress/DownloadStatusBadge'
import React from 'react'
import {useNavigate} from 'react-router-dom'
import {linkAreaHandlers} from '../../lib/linkClicks'
import {EpisodeReadView} from '../../types/schemas/episode'
import {MediaDownloadViewRead} from '../../types/schemas/media_download'
import {DrmBadge} from '../common/DrmProtected'
import {SubscriptionBadge} from '../common/NeedsSubscription'
import {RemovedBadge} from '../common/RemovedFromSource'
import {useEpisodeTags} from '../../lib/queries'
import {episodeTagLabel} from '../../types/schemas/source'
import type {EpisodeFilter} from '../../types/schemas/download_profile'
import {filterSentence, plainText} from '../DownloadProfile/whichEpisodesText'
import {apiUrl} from '../../lib/api'

// Beyond this many downloads for one episode, collapse the rest into a "+N" pill
// instead of letting icons overflow the thumbnail.
const MAX_VISIBLE_DOWNLOAD_ICONS = 4

const LIVE_BADGE_STYLE: React.CSSProperties = {
    position: 'absolute',
    top: 8,
    right: 8,
    zIndex: 2,
    display: 'inline-flex',
    alignItems: 'center',
    gap: 5,
    padding: '4px 8px',
    borderRadius: 999,
    background: 'var(--error, #d64545)',
    color: '#fff',
    boxShadow: '0 1px 4px rgb(0 0 0 / 30%)',
    fontSize: '0.68rem',
    fontWeight: 800,
    letterSpacing: '0.04em',
    lineHeight: 1,
    textTransform: 'uppercase',
}

const LIVE_BADGE_DOT_STYLE: React.CSSProperties = {
    width: 6,
    height: 6,
    flex: '0 0 auto',
    borderRadius: '50%',
    background: 'currentColor',
}

/** What the upgrade check did or will do for an episode's downloads, such as "Better version on Nov 10". */
export function upgradeText(downloads: readonly MediaDownloadViewRead[]): string | null {
    const next = downloads.map((download) => download.upgradeCheckAt).filter((at): at is Date => !!at)
        .sort((a, b) => a.getTime() - b.getTime())[0]
    if (downloads.some((download) => download.upgradeResult === 'upgraded')) return 'Upgraded to a better version'
    if (next) return `Checked for a better version on ${next.toLocaleDateString(undefined, {month: 'short', day: 'numeric'})}`
    if (downloads.some((download) => download.upgradeResult === 'checked')) return 'Checked: no better version'
    return null
}

export function toImageUrl(path?: string | null): string | undefined {
    if (!path) return undefined
    // If already an absolute URL, return as-is
    if (/^https?:\/\//i.test(path)) return path
    const base = apiUrl()
    if (!base) return path
    // If path is already rooted, just prefix API base
    if (path.startsWith('/')) return base + path
    // Default: serve from generic assets path
    return `${base}/assets/${path}`
}

/** Groups a flat list of downloads (e.g. from useCollectionDownloads) by episode slug. */
export function groupDownloadsByEpisodeSlug(
    downloads?: MediaDownloadViewRead[] | null,
): Map<string, MediaDownloadViewRead[]> {
    const map = new Map<string, MediaDownloadViewRead[]>()
    for (const d of downloads ?? []) {
        if (!d.episodeSlug) continue
        const list = map.get(d.episodeSlug)
        if (list) list.push(d)
        else map.set(d.episodeSlug, [d])
    }
    return map
}

function DownloadStatusIcons({downloads}: { downloads: MediaDownloadViewRead[] }) {
    const visibleDownloads = downloads.filter(download => download.presentation.status !== 'not_downloaded')
    if (visibleDownloads.length === 0) return null

    const overflow = visibleDownloads.length > MAX_VISIBLE_DOWNLOAD_ICONS
    const shown = overflow ? visibleDownloads.slice(0, MAX_VISIBLE_DOWNLOAD_ICONS - 1) : visibleDownloads
    const remaining = visibleDownloads.length - shown.length

    return (
        <span className="status-group" role="list" aria-label="Download status">
            {shown.map(download => <DownloadStatusBadge key={download.id} download={download}/>)}
            {remaining > 0 && (
                <span className="status status-more" title={`${remaining} more download(s)`}>+{remaining}</span>
            )}
        </span>
    )
}

const DATE_LABEL = /^(\d{4})-(\d{2})-(\d{2})(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?$/

/** "#12" for a numbered episode; a short date such as "18 Jan 2013" for one a Source numbers by its publish date. */
function episodeBadgeText(label: string): string {
    const date = DATE_LABEL.exec(label)
    if (!date) return `#${label}`
    const [, year, month, day] = date
    return new Date(Number(year), Number(month) - 1, Number(day))
        .toLocaleDateString(undefined, {day: 'numeric', month: 'short', year: 'numeric'})
}

type Props = {
    ep: EpisodeReadView
    collectionSlug: string
    downloads?: MediaDownloadViewRead[]
    /** The Which episodes filter that keeps this episode from downloading automatically. */
    skippedBy?: EpisodeFilter
}

/** The episode thumbnail card used on a show's episode list. */
export default function EpisodeCard({ep, collectionSlug, downloads, skippedBy}: Props) {
    const upgrade = upgradeText(downloads ?? [])
    const initials = ep.title
        .split(' ')
        .map((w) => w[0])
        .join('')
        .slice(0, 3)
        .toUpperCase()

    // Episode thumbnails are landscape by default; if missing/empty, use a placeholder with the episode index.
    const landscapePath = (ep.thumbnailLandscapePath && ep.thumbnailLandscapePath.trim() !== '') ? ep.thumbnailLandscapePath : undefined
    const imageUrl = landscapePath ? toImageUrl(landscapePath) : `https://placehold.co/640x360/png?text=Episode+%23${ep.index}`
    const style = imageUrl ? {backgroundImage: `url(${imageUrl})`} : undefined
    const isLive = String(ep.publishStatus).toLowerCase() === 'live'

    const type = ep.episodeType
    const {data: tags} = useEpisodeTags(ep.sourceKey)
    // Identifier semantics are parsed once by the backend. The card only decides
    // how those semantics should be presented.
    const showNumberBadge = (type === 'ep' || type === 'ep-extra') && !!ep.episodeLabel
    // Every tag other than the main one is badged with its Source's label, such as Short or Livestream.
    const mainTag = tags?.find((tag) => tag.main)?.key ?? 'ep'
    const typeBadgeLabel = type && type !== mainTag && type !== 'ep-extra' ? episodeTagLabel(tags, type) : undefined
    const cornerBadgeText = showNumberBadge ? episodeBadgeText(ep.episodeLabel) : typeBadgeLabel

    const navigate = useNavigate()
    const episodeHref = `/collection/${collectionSlug}/episode/${ep.slug}`
    const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            navigate(episodeHref)
        }
    }

    return (
        <div className="episode-card" role="listitem" aria-label={ep.title} tabIndex={0} onKeyDown={onKeyDown}>
            <div className="cover" style={style} {...linkAreaHandlers(episodeHref, navigate)}>
                <DownloadStatusIcons downloads={downloads ?? []}/>
                {ep.drmProtected ? <DrmBadge onCover/>
                    : ep.needsSubscription ? <SubscriptionBadge sourceKey={ep.sourceKey} onCover/>
                    : ep.removedFromSource && <RemovedBadge onCover/>}
                {isLive && (
                    <span style={LIVE_BADGE_STYLE} aria-label="Episode is live">
                        <span style={LIVE_BADGE_DOT_STYLE} aria-hidden/>
                        Live
                    </span>
                )}
                {/* Show initials only if we are using the placeholder (i.e., no real thumbnail) */}
                {!landscapePath && (
                    <span className="cover-text" aria-hidden>
            {initials}
          </span>
                )}
                {cornerBadgeText && (
                    <span className={`badge badge-${type}`}>{cornerBadgeText}</span>
                )}
            </div>
            <div className="episode-title" title={ep.title}>{ep.title}</div>
            {upgrade && <div className="episode-upgrade">{upgrade}</div>}
            {skippedBy && !(downloads ?? []).some((download) => download.presentation.status !== 'not_downloaded') && (
                <div className="episode-skipped" title="Open the episode to download it anyway">
                    Skipped by filter: {plainText(filterSentence(skippedBy)).replace(/^\w/, (c) => c.toLowerCase())}
                </div>
            )}
        </div>
    )
}
