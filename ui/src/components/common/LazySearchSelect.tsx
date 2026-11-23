import {useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState} from 'react'

import Select, {type SelectGroup} from './Select'

export type LazySearchSelectOption = {
    value: string
    label: string
    selectedLabel?: string
    group?: string
}

type Props = {
    inputId: string
    className?: string
    options: LazySearchSelectOption[]
    value: LazySearchSelectOption | null
    isLoading: boolean
    hasMore: boolean
    hasPrevious?: boolean
    onChange: (option: LazySearchSelectOption) => void
    onSearchChange: (search: string) => void
    onLoadMore: () => void
    onLoadPrevious?: () => void
    placeholder?: string
    noOptionsMessage?: string
    debounceMs?: number
    maxMenuHeight?: number
    ariaLabel?: string
}

export default function LazySearchSelect({
    inputId,
    className,
    options,
    value,
    isLoading,
    hasMore,
    hasPrevious = false,
    onChange,
    onSearchChange,
    onLoadMore,
    onLoadPrevious,
    placeholder = 'Search…',
    noOptionsMessage = 'No results found',
    debounceMs = 250,
    maxMenuHeight = 360,
    ariaLabel,
}: Props) {
    const [inputValue, setInputValue] = useState('')
    const onSearchChangeRef = useRef(onSearchChange)
    const previousPageScrollPosition = useRef<{height: number; top: number} | null>(null)
    const nextPageRequested = useRef(false)
    const menuListRef = useRef<HTMLDivElement | null>(null)
    const paginationState = useRef({
        hasMore,
        hasPrevious,
        isLoading,
        onLoadMore,
        onLoadPrevious,
    })
    paginationState.current = {
        hasMore,
        hasPrevious,
        isLoading,
        onLoadMore,
        onLoadPrevious,
    }

    const menuListElement = () => menuListRef.current

    const handleMenuScroll = useCallback((menuList: HTMLElement) => {
        const {
            hasMore: canLoadMore,
            hasPrevious: canLoadPrevious,
            isLoading: loading,
            onLoadMore: loadMore,
            onLoadPrevious: loadPrevious,
        } = paginationState.current
        if (loading) return

        if (
            menuList.scrollTop <= 1
            && canLoadPrevious
            && loadPrevious
            && previousPageScrollPosition.current === null
        ) {
            previousPageScrollPosition.current = {
                height: menuList.scrollHeight,
                top: menuList.scrollTop,
            }
            loadPrevious()
            return
        }

        const remaining = menuList.scrollHeight - menuList.clientHeight - menuList.scrollTop
        if (remaining <= 1 && canLoadMore && !nextPageRequested.current) {
            nextPageRequested.current = true
            loadMore()
        }
    }, [])

    useEffect(() => {
        onSearchChangeRef.current = onSearchChange
    }, [onSearchChange])

    useEffect(() => {
        if (!isLoading) {
            if (previousPageScrollPosition.current !== null) {
                previousPageScrollPosition.current = null
            }
            nextPageRequested.current = false
        }
    }, [isLoading])

    useEffect(() => {
        const timer = window.setTimeout(() => onSearchChangeRef.current(inputValue), debounceMs)
        return () => window.clearTimeout(timer)
    }, [debounceMs, inputValue])

    const groupedOptions = useMemo<readonly (LazySearchSelectOption | SelectGroup<LazySearchSelectOption>)[]>(() => {
        const groups = new Map<string, LazySearchSelectOption[]>()
        const ungrouped: LazySearchSelectOption[] = []

        for (const option of options) {
            if (!option.group) {
                ungrouped.push(option)
                continue
            }
            const group = groups.get(option.group) ?? []
            group.push(option)
            groups.set(option.group, group)
        }

        return [
            ...ungrouped,
            ...[...groups.entries()].map(([label, groupOptions]) => ({
                label,
                options: groupOptions,
            })),
        ]
    }, [options])

    useLayoutEffect(() => {
        const previousPosition = previousPageScrollPosition.current
        if (previousPosition === null) return

        const menuList = menuListElement()
        previousPageScrollPosition.current = null
        if (!menuList) return

        const addedHeight = menuList.scrollHeight - previousPosition.height
        if (addedHeight <= 0) return

        // Keep the same content at the same visual position. The newly
        // prepended page then exists directly above the current viewport,
        // without triggering another page load until the user scrolls there.
        menuList.scrollTop = previousPosition.top + addedHeight
    }, [groupedOptions])

    useLayoutEffect(() => {
        nextPageRequested.current = false
    }, [groupedOptions])

    return (
        <Select<LazySearchSelectOption>
            inputId={inputId}
            className={className}
            options={groupedOptions}
            value={value}
            inputValue={inputValue}
            onInputChange={(nextValue, {action}) => {
                if (action === 'input-change') setInputValue(nextValue)
            }}
            onChange={(option) => {
                if (!option) return
                setInputValue('')
                onChange(option)
            }}
            onMenuClose={() => {
                previousPageScrollPosition.current = null
                nextPageRequested.current = false
            }}
            menuListRef={menuListRef}
            onMenuListScroll={handleMenuScroll}
            isLoading={isLoading}
            isClearable={false}
            isSearchable
            filterOption={null}
            placeholder={placeholder}
            noOptionsMessage={() => isLoading ? 'Searching…' : noOptionsMessage}
            loadingMessage={() => 'Loading…'}
            maxMenuHeight={maxMenuHeight}
            formatOptionLabel={(option, {context}) => (
                context === 'value' ? (option.selectedLabel ?? option.label) : option.label
            )}
            aria-label={ariaLabel}
        />
    )
}
