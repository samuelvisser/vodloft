import {useCallback, useRef, useState, type KeyboardEvent, type Ref} from 'react'
import ReactSelect, {
    type GroupBase,
    type InputActionMeta,
    type Props as ReactSelectProps,
    type SelectInstance,
} from 'react-select'

type SelectProps<Option, IsMulti extends boolean, Group extends GroupBase<Option>> =
    ReactSelectProps<Option, IsMulti, Group> & {
        ref?: Ref<SelectInstance<Option, IsMulti, Group>>
    }

const NAVIGATION_KEYS = new Set(['ArrowDown', 'ArrowUp', 'PageDown', 'PageUp', 'Home', 'End'])

/**
 * VODLoft's ReactSelect. Every dropdown in the app uses this instead of react-select's own Select,
 * so they all handle the keyboard the same way:
 *
 * - While the user types, no result is highlighted yet.
 * - The first ArrowDown after typing highlights the first result, and Enter chooses it.
 * - After that, the arrow keys move the highlight as usual.
 *
 * react-select itself already focuses the first result while typing, so its first ArrowDown would
 * skip to the second one. The highlight only shows once the user moves it with the keyboard; until
 * then hovering with the mouse shows where a click lands.
 */
export default function Select<
    Option,
    IsMulti extends boolean = false,
    Group extends GroupBase<Option> = GroupBase<Option>,
>({ref, classNamePrefix = 'select', className, onInputChange, onKeyDown, onMenuClose, ...props}: SelectProps<Option, IsMulti, Group>) {
    const selectRef = useRef<SelectInstance<Option, IsMulti, Group> | null>(null)
    const typedSinceNavigation = useRef(false)
    const [keyboardNavigation, setKeyboardNavigation] = useState(false)

    const setRefs = useCallback((instance: SelectInstance<Option, IsMulti, Group> | null) => {
        selectRef.current = instance
        if (typeof ref === 'function') ref(instance)
        else if (ref) ref.current = instance
    }, [ref])

    const handleInputChange = (value: string, meta: InputActionMeta) => {
        if (meta.action === 'input-change') {
            typedSinceNavigation.current = true
            setKeyboardNavigation(false)
        }
        return onInputChange?.(value, meta)
    }

    const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
        onKeyDown?.(event)
        if (event.defaultPrevented || !NAVIGATION_KEYS.has(event.key)) return

        const select = selectRef.current
        const continuesFromTyping = typedSinceNavigation.current
        typedSinceNavigation.current = false
        setKeyboardNavigation(true)

        if (event.key === 'ArrowDown' && continuesFromTyping && select?.props.menuIsOpen) {
            event.preventDefault()
            select.focusOption('first')
        }
    }

    const handleMenuClose = () => {
        typedSinceNavigation.current = false
        setKeyboardNavigation(false)
        onMenuClose?.()
    }

    return (
        <ReactSelect<Option, IsMulti, Group>
            {...props}
            ref={setRefs}
            classNamePrefix={classNamePrefix}
            className={[className, keyboardNavigation ? 'select--keyboard-navigation' : null].filter(Boolean).join(' ') || undefined}
            onInputChange={handleInputChange}
            onKeyDown={handleKeyDown}
            onMenuClose={handleMenuClose}
        />
    )
}
