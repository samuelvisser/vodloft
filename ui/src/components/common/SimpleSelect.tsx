import type {SelectRegistry} from '../../utils/selectRegistry'
import Select, {type SelectOptions, type SingleSelectProps} from './Select'

type SimpleSelectOption = {
    value: string
    label: string
}

type SimpleSelectProps = Omit<
    SingleSelectProps<SimpleSelectOption>,
    'options' | 'value' | 'onChange' | 'isMulti' | 'isSearchable' | 'isClearable'
> & {
    registry: SelectRegistry
    /** Splits the registry's values into parts shown apart, with a line between them. */
    sections?: readonly (readonly string[])[]
    value?: string | null
    onChange?: (value: string) => void
}

/**
 * A registry-backed Select for controls that should behave like a native select:
 * one value, no search, and no clear action.
 *
 * If a selector needs more advanced features such as searching, clearing,
 * multi-select or custom option rendering, use Select directly instead of
 * expanding this intentionally simple component.
 */
export default function SimpleSelect({registry, sections, value, onChange, ...props}: SimpleSelectProps) {
    const selectedOption = registry.options.find((option) => option.value === value) ?? null
    const options: SelectOptions<SimpleSelectOption> = sections
        ? sections.map((values) => ({options: registry.options.filter((option) => values.includes(option.value))}))
        : registry.options
    return (
        <Select<SimpleSelectOption>
            {...props}
            options={options}
            value={selectedOption}
            onChange={(option) => {
                if (option) onChange?.(option.value)
            }}
            isSearchable={false}
            isClearable={false}
        />
    )
}
