import {useEffect, useRef} from 'react'

/**
 * Loads the next part of a scrolling list when its end comes into view. Put `rootRef` on the scrolling
 * element and `endRef` on an element after the last row.
 */
export function useLoadMoreOnScroll<Root extends Element, End extends Element>(
    canLoadMore: boolean,
    loadMore: () => void,
) {
    const rootRef = useRef<Root | null>(null)
    const endRef = useRef<End | null>(null)

    useEffect(() => {
        const node = endRef.current
        if (!node || !canLoadMore) return
        const observer = new IntersectionObserver(
            (entries) => { if (entries[0]?.isIntersecting) loadMore() },
            {root: rootRef.current, rootMargin: '200px'},
        )
        observer.observe(node)
        return () => observer.disconnect()
    }, [canLoadMore, loadMore])

    return {rootRef, endRef}
}
