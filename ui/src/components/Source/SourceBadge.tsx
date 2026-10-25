import {useSourceLookup} from '../../lib/queries'

type SourceBadgeProps = {
    sourceKey?: string | null
    className?: string
}

/** A small label naming the Source an item comes from. */
export default function SourceBadge({sourceKey, className = ''}: SourceBadgeProps) {
    const sources = useSourceLookup()
    if (!sourceKey) return null
    return (
        <span className={`source-badge ${className}`.trim()} data-source={sourceKey}>
            {sources.name(sourceKey)}
        </span>
    )
}
