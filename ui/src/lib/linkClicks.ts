import type {MouseEvent} from 'react'
import type {NavigateFunction} from 'react-router-dom'

// Some clickable areas (table rows, cards) cannot be a single <a> element because they hold their own
// controls. These helpers give such an area the click behaviour of a link: a normal click opens the page,
// while a middle-click or ctrl/cmd-click opens it in a new tab.

const CONTROL_SELECTOR = 'a, button, input, select, textarea, label, [role="switch"], [role="button"], [role="menuitem"]'

/** True when the click landed on a link or control inside the area, which handles the click itself. */
function startedOnInnerControl(event: MouseEvent<HTMLElement>): boolean {
    const control = (event.target as Element | null)?.closest?.(CONTROL_SELECTOR)
    return Boolean(control && control !== event.currentTarget && event.currentTarget.contains(control))
}

function openInNewTab(href: string) {
    window.open(href, '_blank', 'noopener')
}

export function linkAreaHandlers(href: string, navigate: NavigateFunction) {
    return {
        onClick: (event: MouseEvent<HTMLElement>) => {
            if (event.defaultPrevented || startedOnInnerControl(event)) return
            if (event.ctrlKey || event.metaKey) openInNewTab(href)
            else navigate(href)
        },
        // Stop the browser from starting auto-scroll, so the middle-click reaches onAuxClick.
        onMouseDown: (event: MouseEvent<HTMLElement>) => {
            if (event.button === 1 && !startedOnInnerControl(event)) event.preventDefault()
        },
        onAuxClick: (event: MouseEvent<HTMLElement>) => {
            if (event.button !== 1 || event.defaultPrevented || startedOnInnerControl(event)) return
            event.preventDefault()
            openInNewTab(href)
        },
    }
}
