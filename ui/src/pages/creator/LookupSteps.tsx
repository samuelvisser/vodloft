import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'

/** What a creator lookup has done so far: each step done, and the one it is on. */
export default function LookupSteps({steps, first}: {steps: string[], first: string}) {
    return (
        <ol className="creator-lookup-steps" aria-live="polite">
            {(steps.length ? steps : [first]).map((step, index, all) => {
                const current = index === all.length - 1
                return (
                    <li key={step} className={current ? 'is-current' : 'is-done'}>
                        <FontAwesomeIcon icon={current ? faIcon('fass', 'spinner') : faIcon('fass', 'check')} spin={current} fixedWidth/>
                        <span>{step}{current ? '…' : ''}</span>
                    </li>
                )
            })}
        </ol>
    )
}
