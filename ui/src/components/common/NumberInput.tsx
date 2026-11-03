import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {forwardRef, useCallback, useEffect, useRef, type ComponentPropsWithoutRef, type PointerEvent, type ReactNode} from 'react'
import {faIcon} from '../../icons/faIcon'
import './NumberInput.css'

export type NumberInputProps = Omit<ComponentPropsWithoutRef<'input'>, 'type'> & {
    /** Class for the bordered wrapper; `className` styles the inner input. */
    wrapperClassName?: string
    /** Shown inside the field, between the value and the buttons, such as a unit. */
    suffix?: ReactNode
}

const REPEAT_DELAY_MS = 400
const REPEAT_INTERVAL_MS = 70

/**
 * Native number input with VODLoft's own up/down buttons in place of the browser spinners,
 * which differ per engine and clash with the theme. Works with controlled values and with
 * React Hook Form's register(): a step changes the native value and fires a normal input event.
 */
const NumberInput = forwardRef<HTMLInputElement, NumberInputProps>(function NumberInput({
    wrapperClassName,
    suffix,
    className,
    disabled,
    readOnly,
    'aria-invalid': ariaInvalid,
    ...inputProps
}, forwardedRef) {
    const inputRef = useRef<HTMLInputElement | null>(null)
    const repeatTimer = useRef<number | undefined>(undefined)

    const setRef = useCallback((node: HTMLInputElement | null) => {
        inputRef.current = node
        if (typeof forwardedRef === 'function') {
            forwardedRef(node)
        } else if (forwardedRef) {
            forwardedRef.current = node
        }
    }, [forwardedRef])

    const stopRepeat = useCallback(() => {
        window.clearTimeout(repeatTimer.current)
        repeatTimer.current = undefined
    }, [])

    useEffect(() => stopRepeat, [stopRepeat])

    const stepBy = (direction: 1 | -1) => {
        const input = inputRef.current
        if (!input || input.disabled || input.readOnly) return
        const previous = input.value
        try {
            if (direction > 0) input.stepUp()
            else input.stepDown()
        } catch {
            // step="any" has no step base: move by one instead.
            const current = Number.isFinite(input.valueAsNumber) ? input.valueAsNumber : 0
            const min = input.min === '' ? -Infinity : Number(input.min)
            const max = input.max === '' ? Infinity : Number(input.max)
            input.value = String(Math.min(max, Math.max(min, current + direction)))
        }
        if (input.value === previous) return false
        // stepUp() bypasses React's value tracker, so React and RHF see this as user input.
        input.dispatchEvent(new Event('input', {bubbles: true}))
        input.dispatchEvent(new Event('change', {bubbles: true}))
        return true
    }

    const startStepping = (direction: 1 | -1) => (event: PointerEvent<HTMLButtonElement>) => {
        if (event.button !== 0) return
        event.preventDefault()
        // With a mouse, keep typing and arrow keys in the field. On touch, leave focus alone
        // so the on-screen keyboard does not pop up.
        if (event.pointerType === 'mouse') inputRef.current?.focus({preventScroll: true})
        stopRepeat()
        if (stepBy(direction) === false) return
        const repeat = (delay: number) => {
            repeatTimer.current = window.setTimeout(() => {
                if (stepBy(direction) === false) return stopRepeat()
                repeat(REPEAT_INTERVAL_MS)
            }, delay)
        }
        repeat(REPEAT_DELAY_MS)
    }

    const invalid = ariaInvalid === true || ariaInvalid === 'true' ||
        ariaInvalid === 'grammar' || ariaInvalid === 'spelling'
    const inactive = Boolean(disabled || readOnly)

    return (
        <div className={['input', 'number-input', wrapperClassName].filter(Boolean).join(' ')}
             data-invalid={invalid ? 'true' : undefined}
             data-disabled={disabled ? 'true' : undefined}>
            <input
                {...inputProps}
                ref={setRef}
                type="number"
                className={['number-input__input', className].filter(Boolean).join(' ')}
                disabled={disabled}
                readOnly={readOnly}
                aria-invalid={ariaInvalid}
            />
            {suffix != null ? (
                <span
                    className="number-input__suffix"
                    aria-hidden="true"
                    onPointerDown={(event) => {
                        event.preventDefault()
                        inputRef.current?.focus()
                    }}
                >
                    {suffix}
                </span>
            ) : null}
            <span className="number-input__steppers">
                {([1, -1] as const).map((direction) => (
                    <button
                        key={direction}
                        type="button"
                        className="number-input__stepper"
                        tabIndex={-1}
                        disabled={inactive}
                        aria-label={direction > 0 ? 'Increase' : 'Decrease'}
                        onPointerDown={startStepping(direction)}
                        onPointerUp={stopRepeat}
                        onPointerLeave={stopRepeat}
                        onPointerCancel={stopRepeat}
                        onContextMenu={(event) => event.preventDefault()}
                    >
                        <FontAwesomeIcon icon={direction > 0 ? faIcon('fass', 'chevron-up') : faIcon('fass', 'chevron-down')}/>
                    </button>
                ))}
            </span>
        </div>
    )
})

export default NumberInput
