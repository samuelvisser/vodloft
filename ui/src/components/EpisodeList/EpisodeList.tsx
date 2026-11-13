import {useCallback, type ReactNode} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'

import {faIcon} from '../../icons/faIcon'
import {useLoadMoreOnScroll} from '../../lib/useLoadMoreOnScroll'
import {formatBytes} from '../../utils/formatting'
import {formatRunningTime} from '../DownloadProfile/whichEpisodesText'
import './EpisodeList.css'

export type EpisodeListRow = {
    id: number
    title: ReactNode
    /** The small line under the title, such as why the episode is left out. */
    note?: ReactNode
    episodeType?: string | null
    duration?: number | null
    publishedAt?: string | null
    /** Shown in its own column when the list has ``showSize``; null shows nothing there. */
    sizeBytes?: number | null
    /** Shown dimmed, like an episode a filter leaves out. */
    muted?: boolean
} & (
    /** A row with a status icon in front. */
    | {icon: ReactNode, checked?: never, onToggle?: never, toggleLabel?: never}
    /** A row with a checkbox in front; the whole row toggles it. */
    | {icon?: never, checked: boolean, onToggle: () => void, toggleLabel: string}
)

type EpisodeListProps = {
    rows: readonly EpisodeListRow[]
    typeLabel: (key: string) => string
    /** Adds a column with each row's file size. */
    showSize?: boolean
    hasMore: boolean
    loadingMore: boolean
    moreFailed: boolean
    loadMore: () => unknown
    /** The rows are being asked for again: an empty list says it is loading, a full one dims until they come. */
    loading?: boolean
    className?: string
}

/**
 * A scrolling list of episodes with their type, length and date, which loads its next page
 * as its end scrolls into view. Which episodes shows it, and so do the dialogs that pick
 * downloads to delete.
 */
export default function EpisodeList({
    rows, typeLabel, showSize = false, hasMore, loadingMore, moreFailed, loadMore, loading = false, className,
}: EpisodeListProps) {
    const more = useCallback(() => void loadMore(), [loadMore])
    const {rootRef, endRef} = useLoadMoreOnScroll<HTMLUListElement, HTMLLIElement>(hasMore && !loadingMore && !moreFailed, more)

    return (
        <ul
            className={['episode-list', showSize && 'has-size', loading && rows.length > 0 && 'is-refreshing', className].filter(Boolean).join(' ')}
            ref={rootRef} aria-busy={loading}
        >
            {loading && rows.length === 0 && (
                <li className="episode-list-end" role="status">
                    <FontAwesomeIcon icon={faIcon('fass', 'spinner')} spin aria-hidden="true"/> Loading episodes…
                </li>
            )}
            {rows.map((row) => {
                const content = (
                    <>
                        {row.onToggle
                            ? <input type="checkbox" checked={row.checked} onChange={row.onToggle} aria-label={row.toggleLabel}/>
                            : row.icon}
                        <span className="episode-list-main">
                            <span className="episode-list-title">{row.title}</span>
                            {row.note && <span className="episode-list-note">{row.note}</span>}
                        </span>
                        <span className="episode-list-meta">
                            <span>{row.episodeType && <span className="episode-list-type">{typeLabel(row.episodeType)}</span>}</span>
                            <span>{row.duration ? formatRunningTime(row.duration) : null}</span>
                            {showSize && <span>{row.sizeBytes != null ? formatBytes(row.sizeBytes) : null}</span>}
                            <span>
                                {row.publishedAt && new Date(row.publishedAt).toLocaleDateString(undefined, {day: 'numeric', month: 'short', year: 'numeric'})}
                            </span>
                        </span>
                    </>
                )
                return (
                    <li key={row.id} className={row.muted ? 'is-muted' : undefined}>
                        {row.onToggle
                            ? <label className="episode-list-row is-toggle">{content}</label>
                            : <div className="episode-list-row">{content}</div>}
                    </li>
                )
            })}
            {(hasMore || moreFailed) && (
                <li ref={endRef} className="episode-list-end" role="status" aria-busy={loadingMore}>
                    {moreFailed
                        ? <>Couldn’t load more episodes. <button type="button" className="btn" onClick={more}>Try again</button></>
                        : <><FontAwesomeIcon icon={faIcon('fass', 'spinner')} spin aria-hidden="true"/> Loading more episodes…</>}
                </li>
            )}
        </ul>
    )
}
