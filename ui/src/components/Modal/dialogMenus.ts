import {createContext, useContext} from 'react'
import type {CSSObjectWithLabel} from 'react-select'

/** Whether the content around it scrolls inside a dialog, which would cut off a select's menu that opens below it. */
export const InScrollingDialog = createContext(false)

/**
 * The react-select props that open a select's menu on top of the page when the select sits in a scrolling dialog, so
 * the dialog does not cut it off. The menu closes when the dialog's content scrolls, since it would stay behind.
 * A select's own props come after these, so it can still place its menu itself; its own ``styles`` are added to these.
 */
export function useDialogMenuProps() {
    const inDialog = useContext(InScrollingDialog)
    if (!inDialog) return {}
    return {
        menuPortalTarget: document.body,
        menuPlacement: 'auto' as const,
        closeMenuOnScroll: (event: Event) => event.target instanceof Element && event.target.classList.contains('modal-body'),
        // Above the dialog's overlay.
        styles: {menuPortal: (base: CSSObjectWithLabel) => ({...base, zIndex: 1100})},
    }
}
