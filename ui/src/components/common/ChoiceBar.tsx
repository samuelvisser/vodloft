import {type CSSProperties, useId} from 'react'

import './ChoiceBar.css'

export type ChoiceBarOption<T extends string> = {
    value: T
    /** A short word that fits beside a name, such as Own. */
    label: string
    /** What the choice means in full, such as A season of its own, read out and shown on hover. */
    title?: string
}

/**
 * A choice of a few short options, all in view and each one tap away, no bigger than a dropdown. It sits beside the
 * name of what it chooses for, one per row.
 *
 * With ``tiles``, it sets a value for many rows at once instead: the options stand apart as tiles and none shows as
 * chosen, since the rows below each keep their own.
 */
export default function ChoiceBar<T extends string>({value, options, onChange, ariaLabel, tiles = false, disabled = false, className}: {
    value?: T | null
    options: ChoiceBarOption<T>[]
    onChange: (value: T) => void
    ariaLabel: string
    tiles?: boolean
    disabled?: boolean
    className?: string
}) {
    const name = useId()
    if (tiles) {
        return (
            <span role="group" aria-label={ariaLabel} className={`choice-bar is-tiles${className ? ` ${className}` : ''}`}
                  style={{'--choice-count': options.length} as CSSProperties}>
                {options.map((option) => (
                    <button
                        key={option.value} type="button" className="choice-bar-option" disabled={disabled}
                        title={option.title} aria-label={`${ariaLabel}: ${option.title ?? option.label}`}
                        onClick={() => onChange(option.value)}
                    >
                        {option.label}
                    </button>
                ))}
            </span>
        )
    }
    return (
        <span role="radiogroup" aria-label={ariaLabel} className={`choice-bar${className ? ` ${className}` : ''}`}
              style={{'--choice-count': options.length} as CSSProperties}>
            {options.map((option) => (
                <label key={option.value} className={`choice-bar-option${option.value === value ? ' is-chosen' : ''}`} title={option.title}>
                    <input
                        type="radio" name={name} value={option.value} checked={option.value === value} disabled={disabled}
                        aria-label={option.title ?? option.label} onChange={() => onChange(option.value)}
                    />
                    <span aria-hidden="true">{option.label}</span>
                </label>
            ))}
        </span>
    )
}
