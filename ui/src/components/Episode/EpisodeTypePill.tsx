import {useEpisodeTags} from '../../lib/queries'
import {episodeTagLabel} from '../../types/schemas/source'
import './EpisodeTypePill.css'

type Props = {
    sourceKey: string
    /** The episode's type as VODLoft catalogued it, such as aux or trailer. */
    type: string | null
    /** Shows the type as a label on a details line, a coloured dot and the name, instead of a pill. */
    asText?: boolean
}

/** The coloured pill naming an episode's type, such as Auxiliary; nothing for a normal episode. */
export default function EpisodeTypePill({sourceKey, type, asText = false}: Props) {
    const {data: tags} = useEpisodeTags(sourceKey)
    const mainTag = tags?.find((tag) => tag.main)?.key ?? 'ep'
    // A type the Site does not tell apart, such as a yt-dlp video's second episode of one date, is a main one there.
    if (!type || type === mainTag || (tags && !tags.some((tag) => tag.key === type))) return null
    if (asText) {
        return (
            <span className="episode-summary-item episode-summary-label episode-type-label">
                <span className={`episode-type-dot badge-${type}`} aria-hidden="true"/>
                {episodeTagLabel(tags, type)}
            </span>
        )
    }
    return <span className={`badge badge-${type} episode-type-pill`}>{episodeTagLabel(tags, type)}</span>
}
