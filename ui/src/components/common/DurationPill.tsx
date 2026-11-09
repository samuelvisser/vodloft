import {formatClockDuration} from '../../utils/formatting'
import './DurationPill.css'

type Props = {
    /** The length in seconds; nothing shows when it is unknown. */
    seconds: number | null | undefined
    /** The larger size used on an episode or video page's own cover. */
    large?: boolean
}

/** The translucent length pill in the bottom-right corner of a thumbnail. */
export default function DurationPill({seconds, large}: Props) {
    const text = formatClockDuration(seconds)
    if (!text) return null
    return (
        <span className={large ? 'duration-pill duration-pill-large' : 'duration-pill'}>
            <span className="sr-only">Length </span>{text}
        </span>
    )
}
