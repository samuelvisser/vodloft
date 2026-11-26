import {useEffect, useState} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {useQueries} from '@tanstack/react-query'
import {z} from 'zod'

import {faIcon} from '../../icons/faIcon'
import {apiUrl} from '../../lib/api'
import {wordsOf} from '../../lib/collectionWords'
import {CollectionSeasonsReadSchema, SeasonsReviewReadSchema} from '../../types/schemas/collection_seasons'
import SeasonsReview, {GoBack, SavingDoes} from './SeasonsReview'
import {dialogWords, useNarrow} from './seasonsSettings'
import './SeasonsDialog.css'

const BulkReviewSchema = z.object({
    collections: z.object({
        id: z.number(),
        title: z.string(),
        view: CollectionSeasonsReadSchema.nullable().default(null),
        review: SeasonsReviewReadSchema.nullable().default(null),
        /** Why it can't take the changes. */
        skipped: z.string().nullable().default(null),
    }).array(),
})
type BulkReviewItem = z.infer<typeof BulkReviewSchema>['collections'][number]

async function fetchReview(id: number, changes: Record<string, unknown>, signal: AbortSignal) {
    const response = await fetch(`${apiUrl()}/collections/bulk/review`, {
        method: 'POST', headers: {'Content-Type': 'application/json'}, credentials: 'include',
        body: JSON.stringify({ids: [id], changes}), signal,
    })
    if (!response.ok) throw new Error(`Could not look at what changes (HTTP ${response.status})`)
    return BulkReviewSchema.parse(await response.json()).collections
}

/** In a few words, what saving does to one collection, for its folded card. */
function inShort(item: BulkReviewItem): string {
    if (item.skipped || !item.review || !item.view) return ''
    if (item.review.busy) return item.review.busy
    const {season} = dialogWords(wordsOf(item.view.words), item.view)
    const videos = item.view.mediaNames.plural
    const review = item.review
    const moving = (review.moves?.parts ?? []).reduce((sum, part) => sum + part.count, 0)
    const parts = [
        review.newSeasons.length > 0 && `${review.newSeasons.length} new ${review.newSeasons.length === 1 ? season.singular : season.plural}`,
        moving > 0 && `${moving.toLocaleString()} download${moving === 1 ? '' : 's'} move`,
        review.leaving.count > 0 && `${review.leaving.count.toLocaleString()} ${videos} leave`,
        review.deletedFiles.count > 0 && `${review.deletedFiles.count.toLocaleString()} downloaded file${review.deletedFiles.count === 1 ? '' : 's'} deleted`,
    ].filter(Boolean)
    return parts.length ? parts.join(', ') : 'Nothing downloaded moves or leaves'
}

/**
 * The review of the Library's bulk change of seasons settings: what saving does to each chosen collection, as its
 * Seasons dialog's review shows it, one folded card each. Saving can go ahead once every review is in.
 */
export default function BulkSeasonsReview({ids, changes, onReady, onBack}: {
    ids: readonly number[]
    changes: Record<string, unknown>
    onReady: (extra: Record<string, unknown> | null) => void
    onBack: () => void
}) {
    const narrow = useNarrow()
    // The collections that keep their episodes' numbers, as each review's numbering choice says.
    const [keep, setKeep] = useState<number[]>([])
    const [open, setOpen] = useState<number[]>([])
    const reviews = useQueries({
        queries: ids.map((id) => ({
            queryKey: ['collectionsBulkReview', id, changes] as const,
            queryFn: ({signal}: {signal: AbortSignal}) => fetchReview(id, changes, signal),
            staleTime: 0, gcTime: 0, retry: false,
            // A collection VODLoft works on is asked again, as the Seasons dialog's review waits.
            refetchInterval: (query: {state: {data?: BulkReviewItem[]}}) => query.state.data?.some((item) => item.review?.busy) ? 2000 : false,
        })),
    })
    const items = reviews.flatMap((query) => query.data ?? [])
    const pending = reviews.filter((query) => query.isPending).length
    const failed = reviews.find((query) => query.isError)?.error
    const ready = pending === 0 && !failed && !items.some((item) => item.review?.busy)
    const unchanged = ids.length - pending - reviews.filter((query) => query.isError).length - items.length

    useEffect(() => {
        onReady(ready ? {keepNumbers: keep} : null)
    }, [ready, keep]) // eslint-disable-line react-hooks/exhaustive-deps

    const toggle = (id: number) => setOpen((current) => current.includes(id) ? current.filter((x) => x !== id) : [...current, id])
    return (
        <div className="bulk-seasons-review">
            <SavingDoes/>
            <GoBack onBack={onBack}/>
            {failed && <p className="error" role="alert">{failed.message}</p>}
            <ul className="bulk-seasons-review-list">
                {items.map((item) => {
                    // A collection whose downloaded files would be deleted shows it at once.
                    const shown = open.includes(item.id) !== (item.review?.deletedFiles.count ?? 0) > 0
                    const bodyId = `bulk-seasons-review-${item.id}`
                    return (
                        <li key={item.id} className={`bulk-seasons-review-item${item.skipped ? ' is-skipped' : ''}${item.review?.deletedFiles.count ? ' is-danger' : ''}`}>
                            {item.skipped || !item.view ? (
                                <div className="bulk-seasons-review-head">
                                    <FontAwesomeIcon icon={faIcon('fass', 'ban')} aria-hidden="true"/>
                                    <span><b>{item.title}</b><span className="help">Left as it is: {item.skipped}</span></span>
                                </div>
                            ) : (
                                <>
                                    <button type="button" className="bulk-seasons-review-head" aria-expanded={shown} aria-controls={bodyId} onClick={() => toggle(item.id)}>
                                        <FontAwesomeIcon icon={faIcon('fass', shown ? 'chevron-down' : 'chevron-right')} aria-hidden="true"/>
                                        <span><b>{item.title}</b><span className="help">{inShort(item)}</span></span>
                                    </button>
                                    {shown && (
                                        <div id={bodyId} className="bulk-seasons-review-body">
                                            <SeasonsReview
                                                view={item.view} review={item.review ?? undefined} failed={null} changes={[]}
                                                words={dialogWords(wordsOf(item.view.words), item.view)} listName={item.view.creatorListNames.plural}
                                                listing={false} listed={[]} renumber={!keep.includes(item.id)}
                                                onRenumber={(again) => setKeep((current) => again ? current.filter((x) => x !== item.id) : [...current, item.id])}
                                                onBack={onBack} folded={narrow} alone={false}
                                            />
                                        </div>
                                    )}
                                </>
                            )}
                        </li>
                    )
                })}
            </ul>
            {pending > 0 && (
                <p className="change-identification-loading" role="status">
                    <FontAwesomeIcon icon={faIcon('fass', 'spinner')} spin aria-hidden="true"/>
                    Looking at what changes in {pending.toLocaleString()} collection{pending === 1 ? '' : 's'}…
                </p>
            )}
            {unchanged > 0 && (
                <p className="help">
                    {unchanged === 1 ? 'One other collection stays' : `${unchanged.toLocaleString()} other collections stay`} as
                    {unchanged === 1 ? ' it is' : ' they are'}: the changes are what {unchanged === 1 ? 'it has' : 'they have'} already, or {unchanged === 1 ? 'it doesn’t have' : 'they don’t have'} those settings.
                </p>
            )}
        </div>
    )
}
