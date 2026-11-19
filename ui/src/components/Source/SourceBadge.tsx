import {useSourceLookup, useSourcesInUse} from '../../lib/queries'

type SourceBadgeProps = {
    sourceKey?: string | null
    className?: string
}

/** A small label naming the Source an item comes from. While the Library has media from one Source only, it says nothing. */
export default function SourceBadge({sourceKey, className = ''}: SourceBadgeProps) {
    const sources = useSourceLookup()
    const {data: inUse} = useSourcesInUse()
    if (!sourceKey || !inUse || inUse.length < 2) return null
    return (
        <span className={`source-badge ${className}`.trim()} data-source={sourceKey}>
            {sources.name(sourceKey)}
        </span>
    )
}
