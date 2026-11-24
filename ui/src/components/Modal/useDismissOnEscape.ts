import {useEffect, useRef} from 'react'

type OpenModal = {dismiss: () => void, enabled: boolean}

// Open modals, oldest first. Escape only reaches the newest one, so a confirm opened from a dialog closes
// before the dialog under it.
const openModals: OpenModal[] = []

// Escapes pressed in a select whose menu was closed. react-select prevents the default of every Escape, also when it
// had no menu open to close, so those still reach the modal.
const passedOn = new WeakSet<KeyboardEvent>()

function onKeyDownCapture(event: KeyboardEvent) {
    // Seen before the select handles it, while its input still says whether its menu is open.
    const target = event.target
    if (event.key === 'Escape' && target instanceof HTMLElement && target.getAttribute('role') === 'combobox'
        && target.getAttribute('aria-expanded') !== 'true') {
        passedOn.add(event)
    }
}

function onKeyDown(event: KeyboardEvent) {
    // A menu, select or popover inside the modal that handled this Escape itself prevents its default.
    if (event.key !== 'Escape' || (event.defaultPrevented && !passedOn.has(event)) || event.isComposing) return
    const top = openModals[openModals.length - 1]
    if (!top) return
    event.preventDefault()
    if (top.enabled) top.dismiss()
}

/**
 * Lets Escape dismiss a modal while it is open. Escape does what Cancel or Close does, never the modal's main
 * action; pass `enabled` false while dismissing would lose the person's work or break off a running action.
 */
export function useDismissOnEscape(dismiss: () => void, enabled = true, open = true) {
    const entry = useRef<OpenModal>({dismiss, enabled})
    entry.current.dismiss = dismiss
    entry.current.enabled = enabled

    useEffect(() => {
        if (!open) return
        const modal = entry.current
        // The window listener runs after document listeners, so popovers and menus close first.
        if (openModals.length === 0) {
            window.addEventListener('keydown', onKeyDownCapture, true)
            window.addEventListener('keydown', onKeyDown)
        }
        openModals.push(modal)
        return () => {
            openModals.splice(openModals.indexOf(modal), 1)
            if (openModals.length === 0) {
                window.removeEventListener('keydown', onKeyDownCapture, true)
                window.removeEventListener('keydown', onKeyDown)
            }
        }
    }, [open])
}
