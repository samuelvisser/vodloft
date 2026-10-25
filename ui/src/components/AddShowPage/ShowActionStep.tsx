import './ShowActionStep.css'

export type ShowAction = 'index' | 'stream' | 'download' | 'download-stream'

type Props = {
    value?: ShowAction
    onChange: (value: ShowAction) => void
    onBack: () => void
    onContinue: () => void
    onCancel: () => void
    isSubmitting?: boolean
    /** False for a Source that cannot stream episodes it has not downloaded. */
    canStreamFromSource?: boolean
}

const OPTIONS: Array<{
    value: ShowAction
    eyebrow: string
    title: string
    description: string
}> = [
    {
        value: 'index',
        eyebrow: 'Index',
        title: 'Only index this show',
        description: 'Have VODLoft keep track of the show and its episodes, letting you download individual episodes manually.',
    },
    {
        value: 'stream',
        eyebrow: 'Index + Stream',
        title: 'Index and stream this show',
        description: 'Index the show and open a stream you can use with any podcast app to listen to or view episodes externally.',
    },
    {
        value: 'download',
        eyebrow: 'Index + Download',
        title: 'Index and download this show',
        description: 'Index the show and automatically download new episodes to your server using a local media profile.',
    },
    {
        value: 'download-stream',
        eyebrow: 'Index + Download + Stream',
        title: 'Index, download and stream downloaded files',
        description: 'Archive the show and serve it from your own server. VODLoft downloads episodes automatically and exposes them through a stream.',
    },
]

export default function ShowActionStep({value, onChange, onBack, onContinue, onCancel, isSubmitting, canStreamFromSource = true}: Props) {
    const options = canStreamFromSource ? OPTIONS : OPTIONS.filter((option) => option.value !== 'stream')
    return (
        <div className="show-action-step">
            <div className="show-action-heading">
                <h2>What do you want VODLoft to do with this show?</h2>
                <p>Choose how VODLoft should handle new episodes. You can add or change profiles later.</p>
            </div>

            <div className="show-action-options" role="radiogroup" aria-label="Show setup mode">
                {options.map((option, index) => {
                    const selected = value === option.value
                    return (
                        <button
                            key={option.value}
                            type="button"
                            className={`show-action-option${selected ? ' selected' : ''}`}
                            role="radio"
                            aria-checked={selected}
                            onClick={() => onChange(option.value)}
                        >
                            <span className="show-action-number" aria-hidden="true">{index + 1}</span>
                            <span className="show-action-copy">
                                <span className="show-action-eyebrow">{option.eyebrow}</span>
                                <span className="show-action-title">{option.title}</span>
                                <span className="show-action-description">{option.description}</span>
                            </span>
                            <span className="show-action-check" aria-hidden="true">✓</span>
                        </button>
                    )
                })}
            </div>

            <div className="actions">
                <button type="button" className="btn" onClick={onBack}>Back</button>
                <button type="button" className="btn btn-primary" disabled={!value || isSubmitting} onClick={onContinue}>
                    {value === 'index' ? (isSubmitting ? 'Saving…' : 'Save show') : 'Continue'}
                </button>
                <button type="button" className="btn" onClick={onCancel}>Cancel</button>
            </div>
        </div>
    )
}
