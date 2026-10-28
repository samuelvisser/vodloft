import {useState} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import {
    CODEC_NAMES,
    type QuickRules,
    audioOption,
    codecSize,
    qualityBlocked,
    qualityLabel,
    sizeLabel,
} from '../../lib/quickDownloads'
import type {QuickChoice, QuickCodec, QuickDownloadOptions, QuickVideoOption} from '../../types/schemas/quick_download'

type Row =
    | {key: string; kind: 'video'; video: QuickVideoOption}
    | {key: string; kind: 'audio'}

type QuickOptionListProps = {
    options: QuickDownloadOptions
    choice: QuickChoice
    recommended: number | null
    rules: QuickRules
    onChange: (choice: QuickChoice) => void
}

const LOCK_TITLE = 'Not allowed by a rule in Settings › Quick download'

function Chips<T extends string>({values, current, allowed, onPick, label}: {
    values: readonly T[]; current: T | null; allowed: ReadonlySet<string>; onPick: (value: T) => void; label: string
}) {
    return (
        <span className="quick-chips" role="group" aria-label={label}>
            {values.map((value) => {
                const locked = !allowed.has(value)
                return (
                    <button
                        key={value}
                        type="button"
                        className={`quick-chip${current === value ? ' is-on' : ''}${locked ? ' is-locked' : ''}`}
                        aria-pressed={current === value}
                        aria-disabled={locked}
                        title={locked ? LOCK_TITLE : undefined}
                        onClick={(event) => {
                            // A locked chip still lets the click through to its row.
                            if (locked) return
                            event.stopPropagation()
                            onPick(value)
                        }}
                    >
                        {value.toUpperCase()}
                        {locked && <FontAwesomeIcon icon={faIcon('fass', 'lock')} aria-label="locked"/>}
                    </button>
                )
            })}
        </span>
    )
}

/** The codec a row gives with this choice: the chosen one where offered, otherwise the one the Source would pick. */
function rowCodec(video: QuickVideoOption, codec: QuickCodec | null): string | undefined {
    const name = codec && video.codecs.some((c) => c.codec === codec) ? codec : video.codec
    return name ? CODEC_NAMES[name as QuickCodec] ?? name.toUpperCase() : undefined
}

/**
 * What a link can be downloaded as, one row per quality and one for audio,
 * with a size bar where the Source reports sizes. Three rows show at first:
 * Best, the recommended quality from the defaults, and audio. Rules never hide
 * that something exists: a row they rule out is greyed out with the reason.
 * With the choices locked to the defaults, only the chosen row shows.
 */
export default function QuickOptionList({options, choice, recommended, rules, onChange}: QuickOptionListProps) {
    const [showAll, setShowAll] = useState(false)
    const rows: Row[] = [
        ...options.videos.map((video): Row => ({key: `video-${video.quality ?? 'best'}`, kind: 'video', video})),
        {key: 'audio', kind: 'audio'},
    ]
    const featured = new Set(['video-best', `video-${recommended ?? 'best'}`, 'audio'])
    const selectedKey = choice.kind === 'audio' ? 'audio' : `video-${choice.quality ?? 'best'}`
    featured.add(selectedKey)
    const visible = rules.locked
        ? rows.filter((row) => row.key === selectedKey)
        : showAll ? rows : rows.filter((row) => featured.has(row.key))
    const hidden = rows.length - visible.length

    const size = (row: Row) => row.kind === 'audio'
        ? audioOption(options, {...choice, kind: 'audio'})?.sizeBytes
        : codecSize(row.video, choice.codec) ?? row.video.sizeBytes
    const largest = Math.max(0, ...rows.map((row) => size(row) ?? 0))
    const blocked = (row: Row) => row.kind === 'audio'
        ? (!rules.allowed.has('m4a') && !rules.allowed.has('mp3') ? 'audio is not allowed' : null)
        : qualityBlocked(row.video.quality, rules)

    const pick = (row: Row, change: Partial<QuickChoice> = {}) => {
        if (rules.locked || blocked(row)) return
        if (row.kind === 'audio') {
            const audioFormat = change.audioFormat ?? (rules.allowed.has(choice.audioFormat) ? choice.audioFormat : choice.audioFormat === 'm4a' ? 'mp3' : 'm4a')
            onChange({...choice, kind: 'audio', ...change, audioFormat})
        } else {
            onChange({...choice, kind: 'video', quality: (row.video.quality ?? null) as QuickChoice['quality'], ...change})
        }
    }

    return (
        <div className="quick-options" role="radiogroup" aria-label="What to download">
            {visible.map((row) => {
                const selected = row.key === selectedKey
                const rowSize = size(row)
                const reason = blocked(row)
                const isRecommended = row.kind === 'video' && (row.video.quality ?? null) === recommended && recommended != null
                const heldTo = row.kind === 'video' && row.video.quality == null && rules.maxQuality != null && options.formatChoices
                return (
                    <div
                        key={row.key}
                        className={`quick-option${selected ? ' is-selected' : ''}${reason ? ' is-blocked' : ''}`}
                        role="radio"
                        aria-checked={selected}
                        aria-disabled={Boolean(reason) || rules.locked}
                        tabIndex={selected ? 0 : -1}
                        onClick={() => pick(row)}
                        onKeyDown={(event) => {
                            if (event.key === ' ' || event.key === 'Enter') { event.preventDefault(); pick(row) }
                        }}
                    >
                        <span className="quick-option-radio" aria-hidden="true"/>
                        <span className="quick-option-name">
                            <span className="quick-option-title">
                                {row.kind === 'audio' ? 'Audio' : qualityLabel(row.video.quality)}
                                {heldTo && <small className="quick-muted">up to {rules.maxQuality}p</small>}
                                {reason && <small className="quick-muted">{reason}</small>}
                                {isRecommended && !reason && <span className="quick-tag">Recommended</span>}
                            </span>
                            {row.kind === 'video' && options.containers.length > 1 && !reason && (
                                <Chips
                                    label="Video format"
                                    values={options.containers as ('mp4' | 'mkv')[]}
                                    current={selected ? choice.container : null}
                                    allowed={rules.locked ? new Set([choice.container]) : rules.allowed}
                                    onPick={(container) => pick(row, {container})}
                                />
                            )}
                            {row.kind === 'audio' && options.formatChoices && !reason && (
                                <Chips
                                    label="Audio format"
                                    values={['m4a', 'mp3'] as const}
                                    current={selected ? choice.audioFormat : null}
                                    allowed={rules.locked ? new Set([choice.audioFormat]) : rules.allowed}
                                    onPick={(audioFormat) => pick(row, {audioFormat})}
                                />
                            )}
                        </span>
                        <span className="quick-option-codec">
                            {row.kind === 'audio'
                                ? (choice.audioFormat === 'mp3' ? `${choice.audioBitrate ?? 320} kbps` : 'original')
                                : rowCodec(row.video, choice.codec)}
                            {row.kind === 'video' && rules.fixedCodec && options.formatChoices && (
                                <FontAwesomeIcon icon={faIcon('fass', 'lock')} title={`The codec is fixed to ${CODEC_NAMES[rules.fixedCodec]} by a rule in Settings`}/>
                            )}
                        </span>
                        <span className="quick-option-size">
                            {rowSize ? (
                                <>
                                    <span className="quick-option-bar" style={{width: `${Math.max(3, Math.round(rowSize / largest * 100))}%`}}/>
                                    <span>{sizeLabel(rowSize)}</span>
                                </>
                            ) : <span className="quick-muted">size unknown</span>}
                        </span>
                    </div>
                )
            })}
            {!rules.locked && (hidden > 0 || showAll) && rows.length > 3 && (
                <button type="button" className="quick-options-more" onClick={() => setShowAll(!showAll)} aria-expanded={showAll}>
                    {showAll ? 'Show fewer' : `Show all ${rows.length} options`}
                    <FontAwesomeIcon icon={faIcon('fass', showAll ? 'chevron-up' : 'chevron-down')}/>
                </button>
            )}
        </div>
    )
}
