import {forwardRef, useMemo} from 'react'
import Select, {components, type Props as ReactSelectProps, type SelectInstance, type ValueContainerProps} from 'react-select'

import type {SelectRegistry} from '../../utils/selectRegistry'
import {useDialogMenuProps} from '../Modal/dialogMenus'

type SimpleSelectOption = {
    value: string
    label: string
}

type SimpleSelectProps = Omit<
    ReactSelectProps<SimpleSelectOption, false>,
    'options' | 'value' | 'onChange' | 'isMulti' | 'isSearchable' | 'isClearable'
> & {
    registry: SelectRegistry
    value?: string | null
    onChange?: (value: string) => void
    /**
     * Labels the select is made wide enough to show in full, where its parent lets it take its own width (a flex
     * item with `flex-basis: auto`, for one). Give every select in a list the labels of all of them, so the widest
     * one sets the width of each.
     */
    fitLabels?: readonly string[]
}

/**
 * A registry-backed ReactSelect for controls that should behave like a native select:
 * one value, no search, and no clear action.
 *
 * If a selector needs more advanced ReactSelect features such as searching, clearing,
 * multi-select, custom option rendering, or async behavior, use react-select's Select
 * directly instead of expanding this intentionally simple component.
 */
const SimpleSelect = forwardRef<SelectInstance<SimpleSelectOption, false>, SimpleSelectProps>(
    function SimpleSelect({
        registry,
        value,
        onChange,
        classNamePrefix = 'select',
        fitLabels,
        components: customComponents,
        ...props
    }, ref) {
        const dialogMenuProps = useDialogMenuProps()
        const selectedOption = registry.options.find((option) => option.value === value) ?? null
        const fitKey = [...new Set(fitLabels ?? [])].join('\n')
        const selectComponents = useMemo(() => {
            const labels = fitKey ? fitKey.split('\n') : []
            if (!labels.length) return customComponents
            const ValueContainer = customComponents?.ValueContainer ?? components.ValueContainer
            // The labels sit stacked in the value's place, invisible and without height, so the control is as wide as
            // the longest of them in the same font as the value.
            const FittedValueContainer = (containerProps: ValueContainerProps<SimpleSelectOption, false>) => (
                <ValueContainer {...containerProps}>
                    {containerProps.children}
                    <div className="simple-select-fit" aria-hidden="true">
                        {labels.map((label) => <span key={label}>{label}</span>)}
                    </div>
                </ValueContainer>
            )
            return {...customComponents, ValueContainer: FittedValueContainer}
        }, [customComponents, fitKey])

        return (
            <Select<SimpleSelectOption, false>
                {...dialogMenuProps}
                {...props}
                styles={{...dialogMenuProps.styles, ...props.styles}}
                ref={ref}
                classNamePrefix={classNamePrefix}
                components={selectComponents}
                options={registry.options}
                value={selectedOption}
                onChange={(option) => {
                    if (option) onChange?.(option.value)
                }}
                isMulti={false}
                isSearchable={false}
                isClearable={false}
            />
        )
    },
)

export default SimpleSelect
