import './CollectionActionStep.css'

export type CollectionAction = 'index' | 'stream' | 'download' | 'download-stream'

type Props = {
    value?: CollectionAction
    onChange: (value: CollectionAction) => void
    onBack: () => void
    onContinue: () => void
    onCancel: () => void
    isSubmitting?: boolean
    /** False for a Source that cannot stream episodes it has not downloaded. */
    canStreamFromSource?: boolean
}

const OPTIONS: Array<{
    value: CollectionAction
    eyebrow: string
    title: string
    description: string
}> = [
    {
        value: 'index',
        eyebrow: 'Index',
        title: 'Only index this collection',
        description: 'Have VODLoft keep track of the collection and its episodes, letting you download individual episodes manually.',
    },
    {
        value: 'stream',
        eyebrow: 'Index + Stream',
        title: 'Index and stream this collection',
        description: 'Index the collection and open a stream you can use with any podcast app to listen to or view episodes externally.',
    },
    {
        value: 'download',
        eyebrow: 'Index + Download',
        title: 'Index and download this collection',
        description: 'Index the collection and automatically download new episodes to your server using a local media profile.',
    },
    {
        value: 'download-stream',
        eyebrow: 'Index + Download + Stream',
        title: 'Index, download and stream downloaded files',
        description: 'Archive the collection and serve it from your own server. VODLoft downloads episodes automatically and exposes them through a stream.',
    },
]

export default function CollectionActionStep({value, onChange, onBack, onContinue, onCancel, isSubmitting, canStreamFromSource = true}: Props) {
    const options = canStreamFromSource ? OPTIONS : OPTIONS.filter((option) => option.value !== 'stream')
    return (
        <div className="collection-action-step">
            <div className="collection-action-heading">
                <h2>What do you want VODLoft to do with this collection?</h2>
                <p>Choose how VODLoft should handle new episodes. You can add or change profiles later.</p>
            </div>

            <div className="collection-action-options" role="radiogroup" aria-label="Collection setup mode">
                {options.map((option, index) => {
                    const selected = value === option.value
                    return (
                        <button
                            key={option.value}
                            type="button"
                            className={`collection-action-option${selected ? ' selected' : ''}`}
                            role="radio"
                            aria-checked={selected}
                            onClick={() => onChange(option.value)}
                        >
                            <span className="collection-action-number" aria-hidden="true">{index + 1}</span>
                            <span className="collection-action-copy">
                                <span className="collection-action-eyebrow">{option.eyebrow}</span>
                                <span className="collection-action-title">{option.title}</span>
                                <span className="collection-action-description">{option.description}</span>
                            </span>
                            <span className="collection-action-check" aria-hidden="true">✓</span>
                        </button>
                    )
                })}
            </div>

            <div className="actions">
                <button type="button" className="btn" onClick={onBack}>Back</button>
                <button type="button" className="btn btn-primary" disabled={!value || isSubmitting} onClick={onContinue}>
                    {value === 'index' ? (isSubmitting ? 'Saving…' : 'Save collection') : 'Continue'}
                </button>
                <button type="button" className="btn" onClick={onCancel}>Cancel</button>
            </div>
        </div>
    )
}
