import DownloadStatusBadge from '../DownloadProgress/DownloadStatusBadge'
import React from 'react'
import {useLocation, useNavigate} from 'react-router-dom'
import {linkAreaHandlers} from '../../lib/linkClicks'
import {EpisodeReadView} from '../../types/schemas/episode'
import {MediaDownloadViewRead} from '../../types/schemas/media_download'
import {DrmBadge} from '../common/DrmProtected'
import {AccessBadge} from '../common/AccessLocked'
import {RemovedBadge} from '../common/RemovedFromSource'
import {MovedBadge} from './SeasonPlaceNote'
import {apiUrl} from '../../lib/api'
import DurationPill from '../common/DurationPill'
import EpisodeTypePill from './EpisodeTypePill'
import type {CollectionWords} from '../../lib/collectionWords'

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

const SEASON_LABEL = /^S\d+E\d+$/
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
    /** Belongs in another season now, and waits for the user to move it there. */
    moved?: boolean
    /** The title of the episode's collection, for a list of episodes from several collections. */
    collectionTitle?: string
    /** The name of the episode's season, for a list of the episodes of several seasons. */
    seasonName?: string
    /** What the collection calls its seasons and episodes, such as albums and tracks. */
    words: CollectionWords
    /** The collection's own yt-dlp options allow unplayable formats, so its media protected by DRM can still be tried. */
    unplayableAllowed?: boolean
}

/** The episode thumbnail card used on a show's episode list. */
export default function EpisodeCard({ep, collectionSlug, downloads, moved = false, collectionTitle, seasonName, words, unplayableAllowed = false}: Props) {
    // Episode thumbnails are landscape by default; if missing/empty, use a placeholder with the episode index.
    const landscapePath = (ep.thumbnailLandscapePath && ep.thumbnailLandscapePath.trim() !== '') ? ep.thumbnailLandscapePath : undefined
    const imageUrl = landscapePath ? toImageUrl(landscapePath) : `https://placehold.co/640x360/png?text=${encodeURIComponent(words.episode.Singular)}+%23${ep.index}`
    const style = imageUrl ? {backgroundImage: `url(${imageUrl})`} : undefined
    const isLive = String(ep.publishStatus).toLowerCase() === 'live'
    // An episode that has not started yet has no length, so its pill says it is upcoming instead.
    const isUpcoming = ep.publishStatus === 'scheduled' || ep.publishStatus === 'delayed'

    // Identifier semantics are parsed once by the backend. The card only decides
    // how those semantics should be presented: the number of a numbered episode,
    // then its release date, unless the number already is that date.
    // An album's track goes by its number on the album alone, such as Track 3, rather than S01E03.
    const numberText = ep.episodeType === 'ep' && ep.episodeLabel
        ? (words.numberedInSeason && SEASON_LABEL.test(ep.episodeLabel) && ep.episodeNumber
            ? `${words.episode.Singular} ${ep.episodeNumber}`
            : episodeBadgeText(ep.episodeLabel))
        : undefined
    // An episode extra is labelled by its own number, such as #2542.10, in the extras' colour.
    const extraNumber = ep.episodeType === 'ep-extra' && ep.episodeLabel ? episodeBadgeText(ep.episodeLabel) : undefined
    const dateText = ep.publishedDate && !DATE_LABEL.test(ep.episodeLabel)
        ? ep.publishedDate.toLocaleDateString(undefined, {day: 'numeric', month: 'short', year: 'numeric'})
        : undefined
    const metaText = [collectionTitle, seasonName, numberText, dateText].filter(Boolean).join(' · ')

    const routerNavigate = useNavigate()
    const location = useLocation()
    // Opened from its collection's page, the episode's breadcrumb leads back to that page as it was, such as with
    // the season the user picked.
    const fromCollection = location.pathname === `/collection/${collectionSlug}` ? location.pathname + location.search : undefined
    const navigate = (to: string) => routerNavigate(to, {state: fromCollection ? {fromCollection} : undefined})
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
                {ep.drmProtected ? <DrmBadge onCover unplayableAllowed={unplayableAllowed}/>
                    // Media the account may watch only shows its open lock on its own page.
                    : ep.access && !ep.accessGranted ? <AccessBadge label={ep.accessLabel} description={ep.accessDescription} onCover/>
                    : ep.removedFromSource && !ep.removedByRetention ? <RemovedBadge onCover/>
                    : moved && <MovedBadge onCover words={words}/>}
                {isLive && (
                    <span style={LIVE_BADGE_STYLE} aria-label={`${words.episode.Singular} is live`}>
                        <span style={LIVE_BADGE_DOT_STYLE} aria-hidden/>
                        Live
                    </span>
                )}
                {(ep.duration > 0 || isUpcoming) && (
                    <span className="thumb-corner"><DurationPill seconds={ep.duration} upcoming={isUpcoming}/></span>
                )}
            </div>
            <div className="episode-title" title={ep.title}>{ep.title}</div>
            {(metaText || ep.episodeType) && (
                <div className="episode-meta">
                    {extraNumber
                        ? <span className="badge badge-ep-extra episode-type-pill">{extraNumber}</span>
                        : <EpisodeTypePill sourceKey={ep.sourceKey} type={ep.episodeType}/>}
                    {metaText && <span>{metaText}</span>}
                </div>
            )}
        </div>
    )
}
