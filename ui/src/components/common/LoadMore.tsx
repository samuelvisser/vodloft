import {useEffect, useRef} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'

type LoadMoreProps = {
    hasNextPage: boolean
    isFetchingNextPage: boolean
    isFetchNextPageError: boolean
    fetchNextPage: () => unknown
    /** What the list holds, such as "profiles". */
    noun: string
}

/** Loads a list's next page as it scrolls into view, and offers a retry when that fails. */
export default function LoadMore({hasNextPage, isFetchingNextPage, isFetchNextPageError, fetchNextPage, noun}: LoadMoreProps) {
    const sentinel = useRef<HTMLDivElement | null>(null)
    useEffect(() => {
        const node = sentinel.current
        if (!node || !hasNextPage || isFetchingNextPage || isFetchNextPageError) return
        const observer = new IntersectionObserver(
            (entries) => {
                if (entries.some((entry) => entry.isIntersecting)) void fetchNextPage()
            },
            {rootMargin: '600px 0px'},
        )
        observer.observe(node)
        return () => observer.disconnect()
    }, [fetchNextPage, hasNextPage, isFetchNextPageError, isFetchingNextPage])

    if (isFetchNextPageError) {
        return (
            <div className="load-more" role="alert">
                Could not load more {noun}.
                <button type="button" className="btn" onClick={() => void fetchNextPage()}>Try again</button>
            </div>
        )
    }
    if (!hasNextPage) return null
    return (
        <div ref={sentinel} className="load-more" role="status" aria-busy={isFetchingNextPage}>
            {isFetchingNextPage && <><FontAwesomeIcon icon={faIcon('fass', 'circle-notch')} spin/> Loading more {noun}…</>}
        </div>
    )
}
