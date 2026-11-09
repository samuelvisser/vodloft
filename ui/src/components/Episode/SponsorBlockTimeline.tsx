import {SPONSORBLOCK_COLORS, sponsorBlockLabel} from '../../types/sponsorblock'
import './SponsorBlockTimeline.css'

export type SponsorSegment = {category: string; start: number; end: number; action: string}

function clock(seconds: number): string {
    const total = Math.max(0, Math.round(seconds))
    const hours = Math.floor(total / 3600)
    const minutes = Math.floor((total % 3600) / 60)
    const rest = String(total % 60).padStart(2, '0')
    return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${rest}` : `${minutes}:${rest}`
}

/** The seconds cut out, counting overlapping segments once. */
function cutSeconds(segments: SponsorSegment[]): number {
    const cuts = segments.filter((segment) => segment.action === 'cut').sort((a, b) => a.start - b.start)
    let total = 0
    let reach = -Infinity
    for (const {start, end} of cuts) {
        if (end <= reach) continue
        total += end - Math.max(start, reach)
        reach = end
    }
    return total
}

type Props = {
    segments: SponsorSegment[]
    /** The video's length as published, in seconds. */
    duration: number
    title?: string
}

/** The SponsorBlock segments of a download on the video's timeline: what became a chapter and what was cut. */
export default function SponsorBlockTimeline({segments, duration, title}: Props) {
    const length = Math.max(duration, ...segments.map((segment) => segment.end), 1)
    const cut = cutSeconds(segments)
    return (
        <section className="sponsorblock-timeline" aria-label={title ?? 'SponsorBlock'}>
            <h3>{title ?? 'SponsorBlock'}</h3>
            <p className="sponsorblock-timeline__summary">
                {segments.length === 1 ? '1 segment' : `${segments.length} segments`} found.{' '}
                {cut > 0
                    ? <>{clock(cut)} was cut out, so the file is {clock(length - cut)} instead of {clock(length)}.</>
                    : <>Nothing was cut out; the segments are chapters in the file.</>}
            </p>
            <div className="sponsorblock-timeline__bar" role="img"
                 aria-label={`Timeline of ${clock(length)} with ${segments.length} SponsorBlock segments`}>
                {segments.map((segment, index) => {
                    const point = segment.end - segment.start < length / 400
                    return (
                        <span
                            key={index}
                            className={`sponsorblock-timeline__segment is-${segment.action}${point ? ' is-point' : ''}`}
                            title={`${sponsorBlockLabel(segment.category)}, ${clock(segment.start)} to ${clock(segment.end)}`}
                            style={{
                                left: `${(segment.start / length) * 100}%`,
                                width: point ? undefined : `${((segment.end - segment.start) / length) * 100}%`,
                                background: SPONSORBLOCK_COLORS[segment.category] ?? '#94a3b8',
                            }}
                        />
                    )
                })}
            </div>
            <div className="sponsorblock-timeline__scale" aria-hidden="true">
                <span>0:00</span><span>{clock(length)}</span>
            </div>
            <ul className="sponsorblock-timeline__list">
                {segments.map((segment, index) => (
                    <li key={index}>
                        <span className="sponsorblock-timeline__swatch" style={{background: SPONSORBLOCK_COLORS[segment.category] ?? '#94a3b8'}} aria-hidden="true"/>
                        <span className="sponsorblock-timeline__name">{sponsorBlockLabel(segment.category)}</span>
                        <span className="sponsorblock-timeline__time">{clock(segment.start)} to {clock(segment.end)}</span>
                        <span className={`sponsorblock-timeline__action is-${segment.action}`}>
                            {segment.action === 'cut' ? 'Cut out' : 'Chapter'}
                        </span>
                    </li>
                ))}
            </ul>
        </section>
    )
}
