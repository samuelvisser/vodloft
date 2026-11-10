import {formatClockDuration} from '../../utils/formatting'
import './DurationPill.css'

type Props = {
    /** The length in seconds; nothing shows when it is unknown. */
    seconds: number | null | undefined
    /** The larger size used on an episode or video page's own cover. */
    large?: boolean
    /** Shows "Upcoming" in the length's place for an episode that has not started yet. */
    upcoming?: boolean
}

/** The translucent length pill in the bottom-right corner of a thumbnail. */
export default function DurationPill({seconds, large, upcoming}: Props) {
    const text = formatClockDuration(seconds)
    const className = large ? 'duration-pill duration-pill-large' : 'duration-pill'
    if (!text) return upcoming ? <span className={className}>Upcoming</span> : null
    return (
        <span className={className}>
            <span className="sr-only">Length </span>{text}
        </span>
    )
}
