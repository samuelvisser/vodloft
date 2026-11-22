import {
    Fragment,
    useCallback,
    useId,
    useLayoutEffect,
    useMemo,
    useRef,
    useState,
    type CSSProperties,
    type FocusEvent,
    type KeyboardEvent,
    type MouseEvent,
    type ReactNode,
    type RefObject,
} from 'react'

import './Select.css'

export type SelectOption = {value: string; label: string}
export type SelectGroup<O> = {label: string; options: readonly O[]}
export type SelectOptions<O> = readonly (O | SelectGroup<O>)[]
export type SelectOptionState = {isSelected: boolean; isFocused: boolean; isDisabled: boolean}
export type SelectInputAction = 'input-change' | 'input-blur' | 'menu-close' | 'set-value'

type BaseProps<O extends SelectOption> = {
    options: SelectOptions<O>
    inputId?: string
    className?: string
    placeholder?: ReactNode
    isDisabled?: boolean
    isLoading?: boolean
    /** Lets the person type to narrow the options. On by default. */
    isSearchable?: boolean
    isClearable?: boolean
    isOptionDisabled?: (option: O) => boolean
    /** What an option shows in the menu, and as the chosen value in the field. */
    formatOptionLabel?: (option: O, meta: {context: 'menu' | 'value'}) => ReactNode
    classNames?: {
        option?: (option: O) => string | undefined
        singleValue?: (option: O) => string | undefined
    }
    noOptionsMessage?: (meta: {inputValue: string}) => ReactNode
    loadingMessage?: (meta: {inputValue: string}) => ReactNode
    maxMenuHeight?: number
    /** The search text, for a field that keeps it itself. */
    inputValue?: string
    onInputChange?: (value: string, meta: {action: SelectInputAction}) => void
    /** Which options match the search. `null` shows them all, for options searched elsewhere. */
    filterOption?: ((option: O, inputValue: string) => boolean) | null
    onMenuOpen?: () => void
    onMenuClose?: () => void
    onFocus?: (event: FocusEvent<HTMLInputElement>) => void
    onBlur?: (event: FocusEvent<HTMLInputElement>) => void
    autoFocus?: boolean
    openMenuOnFocus?: boolean
    closeMenuOnSelect?: boolean
    /** Leaves the chosen options out of the menu. On by default for a multi select. */
    hideSelectedOptions?: boolean
    /**
     * Labels the select is made wide enough to show in full, where its parent lets it take its own width (a flex
     * item with `flex-basis: auto`, for one). Give every select in a list the labels of all of them, so the widest
     * one sets the width of each.
     */
    fitLabels?: readonly string[]
    /** Wraps an option of the menu, such as to explain why it can't be chosen. */
    renderOption?: (option: ReactNode, data: O, state: SelectOptionState) => ReactNode
    /** Drawn inside the field, behind its value, such as a progress fill. */
    controlAddon?: ReactNode
    /** Takes the place of the chevron. */
    dropdownIndicator?: ReactNode
    menuListRef?: RefObject<HTMLDivElement | null>
    onMenuListScroll?: (list: HTMLDivElement) => void
    'aria-label'?: string
    'aria-invalid'?: boolean
    'aria-describedby'?: string
}

export type SingleSelectProps<O extends SelectOption> = BaseProps<O> & {
    isMulti?: false
    value: O | null | undefined
    onChange: (option: O | null) => void
}

export type MultiSelectProps<O extends SelectOption> = BaseProps<O> & {
    isMulti: true
    value: readonly O[]
    onChange: (options: O[]) => void
}

export type SelectProps<O extends SelectOption> = SingleSelectProps<O> | MultiSelectProps<O>

type Section<O> = {label?: string; options: O[]}

const PAGE_SIZE = 5

const isGroup = <O extends SelectOption>(item: O | SelectGroup<O>): item is SelectGroup<O> => (
    Array.isArray((item as SelectGroup<O>).options)
)

const simplify = (text: string) => text.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().trim()

const matchesSearch = (option: SelectOption, inputValue: string) => (
    simplify(`${option.label} ${option.value}`).includes(simplify(inputValue))
)

const cx = (...names: (string | false | null | undefined)[]) => names.filter(Boolean).join(' ')

// Browsers without anchor positioning (Firefox before 147, Safari before 26) place the menu from script.
const supportsAnchors = typeof CSS !== 'undefined' && CSS.supports?.('position-area: block-end')
const supportsPopover = typeof HTMLElement !== 'undefined' && 'popover' in HTMLElement.prototype
const MENU_GAP = 8

function placeMenuFromScript(control: HTMLElement, menu: HTMLElement, list: HTMLElement | null, maxMenuHeight: number) {
    const rect = control.getBoundingClientRect()
    const viewportHeight = window.visualViewport?.height ?? window.innerHeight
    const below = viewportHeight - rect.bottom - MENU_GAP * 2
    const above = rect.top - MENU_GAP * 2
    menu.style.margin = '0'
    if (list) list.style.maxHeight = `${maxMenuHeight}px`
    const height = menu.offsetHeight
    // Below when it fits, above when only that fits, and otherwise on the side with more room, made shorter to fit.
    const placeBelow = height <= below || (height > above && below >= above)
    const room = Math.max(0, placeBelow ? below : above)
    if (list && height > room) list.style.maxHeight = `${Math.max(0, maxMenuHeight - (height - room))}px`
    menu.style.left = `${rect.left}px`
    menu.style.width = `${rect.width}px`
    menu.style.top = placeBelow
        ? `${rect.bottom + MENU_GAP}px`
        : `${rect.top - MENU_GAP - menu.offsetHeight}px`
}

function ChevronIcon() {
    return (
        <svg height="20" width="20" viewBox="0 0 20 20" aria-hidden="true" focusable="false">
            <path d="M4.516 7.548c0.436-0.446 1.043-0.481 1.576 0l3.908 3.747 3.908-3.747c0.533-0.481 1.141-0.446 1.574 0 0.436 0.445 0.408 1.197 0 1.615-0.406 0.418-4.695 4.502-4.695 4.502-0.217 0.223-0.502 0.335-0.787 0.335s-0.57-0.112-0.789-0.335c0 0-4.287-4.084-4.695-4.502s-0.436-1.17 0-1.615z"/>
        </svg>
    )
}

function CrossIcon({size = 20}: {size?: number}) {
    return (
        <svg height={size} width={size} viewBox="0 0 20 20" aria-hidden="true" focusable="false">
            <path d="M14.348 14.849c-0.469 0.469-1.229 0.469-1.697 0l-2.651-3.030-2.651 3.029c-0.469 0.469-1.229 0.469-1.697 0-0.469-0.469-0.469-1.229 0-1.697l2.758-3.15-2.759-3.152c-0.469-0.469-0.469-1.228 0-1.697s1.228-0.469 1.697 0l2.652 3.031 2.651-3.031c0.469-0.469 1.228-0.469 1.697 0s0.469 1.229 0 1.697l-2.758 3.152 2.758 3.15c0.469 0.469 0.469 1.229 0 1.698z"/>
        </svg>
    )
}

/**
 * VODLoft's dropdown: one or several values, optionally searchable and clearable, with groups and options that
 * can't be chosen. The menu opens in the browser's top layer, so a dialog, a card or a scrolling parent never clips
 * it, and CSS anchor positioning keeps it attached to the field while the page scrolls.
 *
 * It follows the ARIA combobox pattern: the field is a text input with the combobox role, the menu a listbox, and
 * the arrow keys move through the options while focus stays in the field.
 */
export default function Select<O extends SelectOption>(props: SelectProps<O>) {
    const {
        options,
        inputId,
        className,
        placeholder = 'Select…',
        isDisabled = false,
        isLoading = false,
        isSearchable = true,
        isClearable = false,
        isOptionDisabled,
        formatOptionLabel,
        classNames,
        noOptionsMessage,
        loadingMessage,
        maxMenuHeight = 300,
        filterOption,
        onMenuOpen,
        onMenuClose,
        onFocus,
        onBlur,
        autoFocus,
        openMenuOnFocus = false,
        closeMenuOnSelect = true,
        fitLabels,
        renderOption,
        controlAddon,
        dropdownIndicator,
        menuListRef,
        onMenuListScroll,
    } = props
    const multi = props.isMulti === true
    const hideSelected = props.hideSelectedOptions ?? multi
    const selected = useMemo<readonly O[]>(
        () => (props.isMulti ? props.value : props.value ? [props.value] : []),
        [props.isMulti, props.value],
    )
    const selectedKeys = useMemo(() => new Set(selected.map((option) => option.value)), [selected])

    const generatedId = useId().replace(/[^a-zA-Z0-9_-]/g, '')
    const baseId = `vl-select-${generatedId}`
    const id = inputId ?? `${baseId}-input`
    const listboxId = `${baseId}-listbox`

    const [open, setOpen] = useState(false)
    const [focused, setFocused] = useState(false)
    const [ownInput, setOwnInput] = useState('')
    const [focusedKey, setFocusedKey] = useState<string | null>(null)
    const [announcement, setAnnouncement] = useState('')
    const inputValue = props.inputValue ?? ownInput

    const inputRef = useRef<HTMLInputElement>(null)
    const controlRef = useRef<HTMLDivElement>(null)
    const menuRef = useRef<HTMLDivElement | null>(null)
    const listRef = useRef<HTMLDivElement | null>(null)
    // Set when the menu opens: the chosen option is centred once it is in the menu, which for a lazily loaded list
    // can be a page later.
    const centerSelected = useRef(false)
    // Set when the keyboard moves the focus: that option is scrolled into view.
    const scrollToFocus = useRef(false)

    const optionDisabled = useCallback((option: O) => isOptionDisabled?.(option) ?? false, [isOptionDisabled])
    const format = (option: O, context: 'menu' | 'value') => (
        formatOptionLabel ? formatOptionLabel(option, {context}) : option.label
    )

    const {sections, enabled, positions} = useMemo(() => {
        const filter = filterOption === null ? null : (filterOption ?? matchesSearch)
        const keep = (option: O) => (
            !(hideSelected && selectedKeys.has(option.value)) && (!filter || !inputValue || filter(option, inputValue))
        )
        const result: Section<O>[] = []
        for (const item of options) {
            if (isGroup(item)) {
                const kept = item.options.filter(keep)
                if (kept.length) result.push({label: item.label, options: kept})
            } else if (keep(item)) {
                const last = result[result.length - 1]
                if (last && last.label === undefined) last.options.push(item)
                else result.push({options: [item]})
            }
        }
        const shown = result.flatMap((section) => section.options)
        const positions = new Map(shown.map((option, index) => [option, index]))
        return {sections: result, enabled: shown.filter((option) => !optionDisabled(option)), positions}
    }, [filterOption, hideSelected, inputValue, optionDisabled, options, selectedKeys])

    // The option the keyboard is on: the one last moved to while it is still in the menu, otherwise the first.
    const focusedOption = open
        ? (enabled.find((option) => option.value === focusedKey) ?? enabled[0] ?? null)
        : null

    const changeInput = (next: string, action: SelectInputAction) => {
        if (props.inputValue === undefined) setOwnInput(next)
        props.onInputChange?.(next, {action})
    }

    const openMenu = () => {
        if (open || isDisabled) return
        const current = !multi ? selected[0] : undefined
        setFocusedKey(current && !optionDisabled(current) ? current.value : null)
        centerSelected.current = !multi && !!current
        setOpen(true)
        onMenuOpen?.()
    }

    const closeMenu = () => {
        if (!open) return
        setOpen(false)
        setFocusedKey(null)
        centerSelected.current = false
        if (inputValue) changeInput('', 'menu-close')
        onMenuClose?.()
    }

    const choose = (option: O) => {
        if (optionDisabled(option)) return
        if (props.isMulti) {
            const removing = selectedKeys.has(option.value)
            if (!removing && hideSelected) {
                // The chosen option leaves the menu: the keyboard moves on to its neighbour.
                const index = enabled.indexOf(option)
                setFocusedKey((enabled[index + 1] ?? enabled[index - 1])?.value ?? null)
            }
            props.onChange(removing ? selected.filter((item) => item.value !== option.value) : [...selected, option])
            setAnnouncement(`option ${option.label}, ${removing ? 'deselected' : 'selected'}.`)
        } else {
            props.onChange(option)
            setAnnouncement(`option ${option.label}, selected.`)
        }
        if (inputValue) changeInput('', 'set-value')
        if (!multi || closeMenuOnSelect) {
            closeMenu()
            // On a phone, the keyboard goes away once a value is chosen.
            if (!multi && window.matchMedia?.('(pointer: coarse)').matches) inputRef.current?.blur()
        }
    }

    const remove = (option: O) => {
        if (!props.isMulti) return
        props.onChange(selected.filter((item) => item.value !== option.value))
        setAnnouncement(`option ${option.label}, deselected.`)
    }

    const clear = () => {
        if (props.isMulti) props.onChange([])
        else props.onChange(null)
        setAnnouncement('All selected options have been cleared.')
    }

    const moveFocus = (to: 'first' | 'last' | number, wrap = false) => {
        if (!enabled.length) return
        let index: number
        if (to === 'first') index = 0
        else if (to === 'last') index = enabled.length - 1
        else {
            const current = focusedOption ? enabled.indexOf(focusedOption) : -1
            index = current + to
            if (wrap) index = (index + enabled.length) % enabled.length
            else index = Math.min(enabled.length - 1, Math.max(0, index))
        }
        scrollToFocus.current = true
        setFocusedKey(enabled[index].value)
    }

    const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
        if (isDisabled || event.nativeEvent.isComposing) return
        switch (event.key) {
            case 'ArrowDown':
            case 'ArrowUp':
                event.preventDefault()
                if (!open) openMenu()
                else moveFocus(event.key === 'ArrowDown' ? 1 : -1, true)
                return
            case 'PageDown':
            case 'PageUp':
                if (!open) return
                event.preventDefault()
                moveFocus(event.key === 'PageDown' ? PAGE_SIZE : -PAGE_SIZE)
                return
            case 'Home':
            case 'End':
                if (!open || inputValue) return
                event.preventDefault()
                moveFocus(event.key === 'Home' ? 'first' : 'last')
                return
            case 'Enter':
                if (!open) return
                event.preventDefault()
                if (focusedOption) choose(focusedOption)
                return
            case 'Escape':
                if (!open) return
                // Keeps a modal around the field open: Escape only closes the menu.
                event.preventDefault()
                event.stopPropagation()
                closeMenu()
                return
            case 'Tab':
                // Moving on with the keyboard keeps the option it moved to, as a native select does.
                if (open && !multi && focusedOption && !selectedKeys.has(focusedOption.value)) choose(focusedOption)
                else closeMenu()
                return
            case ' ':
                if (inputValue) return
                event.preventDefault()
                if (!open) openMenu()
                else if (focusedOption) choose(focusedOption)
                return
            case 'Backspace':
                if (inputValue || !selected.length) return
                if (multi) {
                    event.preventDefault()
                    remove(selected[selected.length - 1])
                } else if (isClearable) {
                    event.preventDefault()
                    clear()
                }
        }
    }

    const onControlMouseDown = (event: MouseEvent<HTMLDivElement>) => {
        if (isDisabled || event.button !== 0) return
        const onInput = event.target === inputRef.current
        if (!onInput) event.preventDefault()
        if (document.activeElement !== inputRef.current) inputRef.current?.focus()
        if (!open) openMenu()
        else if (!onInput || !isSearchable) closeMenu()
    }

    const setMenu = useCallback((element: HTMLDivElement | null) => {
        menuRef.current = element
        if (element && supportsPopover && !element.matches(':popover-open')) {
            try {
                element.showPopover()
            } catch {
                // A menu that is no longer in the document can't open; the next render replaces it.
            }
        }
    }, [])

    const setList = useCallback((element: HTMLDivElement | null) => {
        listRef.current = element
        if (menuListRef) menuListRef.current = element
    }, [menuListRef])

    // Centre the chosen option when the menu opens, and keep the option the keyboard moves to in view.
    useLayoutEffect(() => {
        const list = listRef.current
        if (!open || !list) return
        if (centerSelected.current) {
            const chosen = list.querySelector<HTMLElement>('.select__option--is-selected')
            if (chosen) {
                centerSelected.current = false
                list.scrollTop = chosen.offsetTop + chosen.offsetHeight / 2 - list.clientHeight / 2
            }
        }
        if (scrollToFocus.current) {
            scrollToFocus.current = false
            const option = list.querySelector<HTMLElement>('.select__option--is-focused')
            if (!option) return
            if (option.offsetTop < list.scrollTop) list.scrollTop = option.offsetTop
            else if (option.offsetTop + option.offsetHeight > list.scrollTop + list.clientHeight) {
                list.scrollTop = option.offsetTop + option.offsetHeight - list.clientHeight
            }
        }
    })

    // Without anchor positioning the menu follows the field from script while it is open.
    useLayoutEffect(() => {
        if (!open || supportsAnchors) return
        const control = controlRef.current
        const menu = menuRef.current
        if (!control || !menu || !supportsPopover) return
        let frame = 0
        const place = () => placeMenuFromScript(control, menu, listRef.current, maxMenuHeight)
        const schedule = () => {
            cancelAnimationFrame(frame)
            frame = requestAnimationFrame(place)
        }
        place()
        window.addEventListener('scroll', schedule, true)
        window.addEventListener('resize', schedule)
        window.visualViewport?.addEventListener('resize', schedule)
        const observer = new ResizeObserver(schedule)
        observer.observe(menu)
        observer.observe(control)
        return () => {
            cancelAnimationFrame(frame)
            window.removeEventListener('scroll', schedule, true)
            window.removeEventListener('resize', schedule)
            window.visualViewport?.removeEventListener('resize', schedule)
            observer.disconnect()
        }
    }, [maxMenuHeight, open])

    const hasValue = selected.length > 0
    const singleValue = !multi && hasValue && !inputValue ? selected[0] : null
    const labels = fitLabels?.length ? [...new Set(fitLabels)] : null
    const optionId = (option: O) => `${listboxId}-option-${positions.get(option)}`

    const renderMenuOption = (option: O) => {
        const state: SelectOptionState = {
            isSelected: selectedKeys.has(option.value),
            isFocused: focusedOption === option,
            isDisabled: optionDisabled(option),
        }
        const node = (
            <div
                id={optionId(option)}
                role="option"
                aria-selected={state.isSelected}
                aria-disabled={state.isDisabled || undefined}
                className={cx(
                    'select__option',
                    state.isFocused && 'select__option--is-focused',
                    state.isSelected && 'select__option--is-selected',
                    state.isDisabled && 'select__option--is-disabled',
                    classNames?.option?.(option),
                )}
                onClick={() => choose(option)}
                onMouseMove={() => {
                    if (!state.isDisabled && !state.isFocused) setFocusedKey(option.value)
                }}
            >
                {format(option, 'menu')}
            </div>
        )
        return <Fragment key={option.value}>{renderOption ? renderOption(node, option, state) : node}</Fragment>
    }

    const notice = isLoading
        ? (loadingMessage?.({inputValue}) ?? 'Loading…')
        : (noOptionsMessage?.({inputValue}) ?? 'No options')

    const menu = open && (
        <div
            ref={setMenu}
            popover={supportsPopover ? 'manual' : undefined}
            className={cx('select__menu', !supportsPopover && 'select__menu--in-place')}
            // Keeps the focus in the field, so a click on an option doesn't close the menu first.
            onMouseDown={(event) => event.preventDefault()}
        >
            <div
                ref={setList}
                id={listboxId}
                role="listbox"
                aria-label={props['aria-label']}
                aria-multiselectable={multi || undefined}
                className="select__menu-list"
                style={{'--select-menu-max-height': `${maxMenuHeight}px`} as CSSProperties}
                onScroll={(event) => onMenuListScroll?.(event.currentTarget)}
            >
                {sections.map((section, index) => {
                    if (section.label === undefined) {
                        return <Fragment key={`options-${index}`}>{section.options.map(renderMenuOption)}</Fragment>
                    }
                    const headingId = `${listboxId}-group-${index}`
                    return (
                        <div key={`group-${section.label}`} className="select__group" role="group" aria-labelledby={headingId}>
                            <div id={headingId} className="select__group-heading">{section.label}</div>
                            {section.options.map(renderMenuOption)}
                        </div>
                    )
                })}
                {sections.length === 0 && (
                    <div className={cx('select__menu-notice', isLoading ? 'select__menu-notice--loading' : 'select__menu-notice--no-options')}>
                        {notice}
                    </div>
                )}
            </div>
        </div>
    )

    return (
        <div
            className={cx('select', className, isDisabled && 'select--is-disabled')}
            style={{'--select-anchor': `--${baseId}`} as CSSProperties}
        >
            <span className="select__live-region" aria-live="polite" aria-atomic="true">
                {focused ? announcement : ''}
            </span>
            <div
                ref={controlRef}
                className={cx(
                    'select__control',
                    focused && 'select__control--is-focused',
                    open && 'select__control--menu-is-open',
                    isDisabled && 'select__control--is-disabled',
                )}
                onMouseDown={onControlMouseDown}
            >
                {controlAddon}
                <div className={cx(
                    'select__value-container',
                    multi && 'select__value-container--is-multi',
                    hasValue && 'select__value-container--has-value',
                )}>
                    {!hasValue && !inputValue && <div className="select__placeholder">{placeholder}</div>}
                    {singleValue && (
                        <div className={cx('select__single-value', classNames?.singleValue?.(singleValue))}>
                            {format(singleValue, 'value')}
                        </div>
                    )}
                    {multi && selected.map((option) => (
                        <div key={option.value} className="select__multi-value">
                            <div className="select__multi-value__label">{format(option, 'value')}</div>
                            {!isDisabled && (
                                <div
                                    role="button"
                                    className="select__multi-value__remove"
                                    aria-label={`Remove ${option.label}`}
                                    onMouseDown={(event) => {
                                        event.preventDefault()
                                        event.stopPropagation()
                                    }}
                                    onClick={(event) => {
                                        event.stopPropagation()
                                        remove(option)
                                    }}
                                >
                                    <CrossIcon size={14}/>
                                </div>
                            )}
                        </div>
                    ))}
                    <div className={cx('select__input-container', !isSearchable && 'select__input-container--read-only')} data-value={inputValue}>
                        <input
                            ref={inputRef}
                            id={id}
                            className="select__input"
                            type="text"
                            role="combobox"
                            aria-expanded={open}
                            aria-haspopup="listbox"
                            aria-controls={open ? listboxId : undefined}
                            aria-autocomplete={isSearchable ? 'list' : 'none'}
                            aria-activedescendant={focusedOption ? optionId(focusedOption) : undefined}
                            aria-label={props['aria-label']}
                            aria-invalid={props['aria-invalid'] || undefined}
                            aria-describedby={props['aria-describedby']}
                            readOnly={!isSearchable}
                            inputMode={isSearchable ? undefined : 'none'}
                            disabled={isDisabled}
                            autoFocus={autoFocus}
                            autoComplete="off"
                            autoCapitalize="none"
                            autoCorrect="off"
                            spellCheck={false}
                            value={inputValue}
                            onChange={(event) => {
                                if (!isSearchable) return
                                changeInput(event.target.value, 'input-change')
                                setFocusedKey(null)
                                if (!open) openMenu()
                            }}
                            onKeyDown={onKeyDown}
                            onFocus={(event) => {
                                setFocused(true)
                                onFocus?.(event)
                                if (openMenuOnFocus) openMenu()
                            }}
                            onBlur={(event) => {
                                setFocused(false)
                                setAnnouncement('')
                                if (open) closeMenu()
                                else if (inputValue) changeInput('', 'input-blur')
                                onBlur?.(event)
                            }}
                        />
                    </div>
                    {labels && (
                        // The labels sit stacked in the value's place, invisible and without height, so the control
                        // is as wide as the longest of them in the same font as the value.
                        <div className="simple-select-fit" aria-hidden="true">
                            {labels.map((label) => <span key={label}>{label}</span>)}
                        </div>
                    )}
                </div>
                <div className="select__indicators">
                    {isClearable && hasValue && !isDisabled && (
                        <div
                            className="select__indicator select__clear-indicator"
                            aria-hidden="true"
                            onMouseDown={(event) => {
                                if (event.button !== 0) return
                                event.preventDefault()
                                event.stopPropagation()
                                clear()
                                inputRef.current?.focus()
                            }}
                        >
                            <CrossIcon/>
                        </div>
                    )}
                    {isLoading && (
                        <div className="select__indicator select__loading-indicator" aria-hidden="true">
                            <span/><span/><span/>
                        </div>
                    )}
                    <span className="select__indicator-separator"/>
                    {dropdownIndicator ?? (
                        <div className="select__indicator select__dropdown-indicator" aria-hidden="true">
                            <ChevronIcon/>
                        </div>
                    )}
                </div>
            </div>
            {menu}
        </div>
    )
}
