import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import type {ProgressStep} from '../../types/progress'

const ICONS = {
    pending: faIcon('fass', 'circle'), running: faIcon('fass', 'spinner'), waiting: faIcon('fass', 'spinner'),
    completed: faIcon('fass', 'check'), failed: faIcon('fass', 'circle-xmark'), canceled: faIcon('fass', 'xmark'),
}

/** The plan of a creator lookup: each step done, those it is on with how many of how many where they count, and
 * those still to come. A step skipped because the creator has nothing there, such as Shorts, is left out. ``first``
 * stands in until the plan arrives. */
export default function LookupSteps({steps, first}: {steps: ProgressStep[], first: string}) {
    const shown = steps.filter((step) => step.state !== 'skipped')
    const list = shown.length ? shown : [{id: 'first', label: first, state: 'running', percent: null} satisfies ProgressStep]
    return (
        <ol className="creator-lookup-steps" aria-live="polite">
            {list.map((step) => {
                const current = step.state === 'running' || step.state === 'waiting'
                return (
                    <li key={step.id} className={`is-${current ? 'current' : step.state === 'completed' ? 'done' : step.state}`}>
                        <FontAwesomeIcon icon={ICONS[step.state as keyof typeof ICONS]} spin={current} fixedWidth/>
                        <span>{step.label}{current && step.count ? ` (${step.count})` : ''}{current ? '…' : ''}</span>
                    </li>
                )
            })}
        </ol>
    )
}
