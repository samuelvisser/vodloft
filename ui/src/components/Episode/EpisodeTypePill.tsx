import {useEpisodeTags} from '../../lib/queries'
import {episodeTagLabel} from '../../types/schemas/source'
import './EpisodeTypePill.css'

type Props = {
    sourceKey: string
    /** The episode's type as VODLoft catalogued it, such as aux or trailer. */
    type: string | null
}

/** The coloured pill naming an episode's type, such as Auxiliary; nothing for a normal episode. */
export default function EpisodeTypePill({sourceKey, type}: Props) {
    const {data: tags} = useEpisodeTags(sourceKey)
    const mainTag = tags?.find((tag) => tag.main)?.key ?? 'ep'
    if (!type || type === mainTag) return null
    return <span className={`badge badge-${type} episode-type-pill`}>{episodeTagLabel(tags, type)}</span>
}
