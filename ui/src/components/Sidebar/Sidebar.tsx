import {useLayoutEffect, useRef, useState} from 'react'
import {NavLink} from 'react-router-dom'
import Footer from './Footer'
import Navbar from './Navbar'
import DownloadsActivity from './DownloadsActivity'
import type { NavItem } from './navTypes'
import {faIcon} from '../../icons/faIcon'
import {can, canAnySettings} from '../../lib/access'


const items: NavItem[] = [
    {path: '/', label: 'Home', icon: faIcon('fass', 'house'), end: true, access: ['library']},
    {path: '/library', label: 'Library', icon: faIcon('fass', 'books'), access: ['library']},
    {path: '/browse', label: 'Browse', icon: faIcon('fass', 'magnifying-glass'), access: () => can('add_media') && !can('library')},
    {path: '/quick-download', label: 'Quick download', icon: faIcon('fass', 'bolt'), access: ['quick_downloads']},
    {path: '/downloads', label: 'Downloads', icon: faIcon('fass', 'circle-down'), access: ['managed_downloads'], iconOverlay: DownloadsActivity},
    {
        label: 'Profiles',
        icon: faIcon('fass', 'layer-group'),
        children: [
            { path: '/local-media-profiles', label: 'Local Media Profiles', icon: faIcon('fass', 'file-video'), access: ['local_media_profiles'] },
            { path: '/download-profiles', label: 'Download Profiles', icon: faIcon('fass', 'download'), access: ['download_profiles'] },
            { path: '/stream-profiles', label: 'Stream Profiles', icon: faIcon('fass', 'rss'), access: ['stream_profiles'] },
        ]
    },
    {
        label: 'Config',
        icon: faIcon('fass', 'sliders'),
        children: [
            {path: '/settings', label: 'Settings', icon: faIcon('fass', 'gear'), access: () => canAnySettings()},
            {path: '/tasks', label: 'Tasks', icon: faIcon('fass', 'bars-progress'), access: ['tasks']},
            {path: '/logs', label: 'Log', icon: faIcon('fass', 'rectangle-history'), access: ['logs']},
        ],
    },
]

// How far the desktop sidebar shrinks its footer to fit the window height, in order: the full footer;
// the footer links side by side; the footer icons and version on one row; and no footer, with its icons
// next to the logo. The navigation only scrolls when even the last one is too tall. The logo size follows
// the window height alone (index.css), so opening a submenu never moves the items above it.
const FITS = ['roomy', 'compact', 'icons', 'header'] as const
type SidebarFit = typeof FITS[number]

function useSidebarFit() {
    const sidebarRef = useRef<HTMLElement>(null)
    const innerRef = useRef<HTMLDivElement>(null)
    const navRef = useRef<HTMLElement>(null)
    const [fit, setFit] = useState<SidebarFit>('roomy')

    useLayoutEffect(() => {
        const sidebar = sidebarRef.current
        const inner = innerRef.current
        const nav = navRef.current
        if (!sidebar || !inner || !nav) return

        // Try each fit from roomy to the last and keep the first one where the navigation does not overflow.
        // It measures the navigation itself, so it keeps working when items are added or removed.
        // Setting the attribute directly lets every try be measured before the browser paints.
        const update = () => {
            let chosen: SidebarFit = FITS[FITS.length - 1]
            for (const candidate of FITS) {
                sidebar.dataset.fit = candidate
                if (inner.scrollHeight <= inner.clientHeight) {
                    chosen = candidate
                    break
                }
            }
            sidebar.dataset.fit = chosen
            setFit(chosen)
        }

        update()
        // The window height changes the room; opening a submenu changes what has to fit.
        const observer = new ResizeObserver(update)
        observer.observe(sidebar)
        observer.observe(nav)
        return () => observer.disconnect()
    }, [])

    return {sidebarRef, innerRef, navRef, fit}
}

export default function Sidebar() {
    const {sidebarRef, innerRef, navRef, fit} = useSidebarFit()

    return (
        <aside className="sidebar" aria-label="Sidebar" ref={sidebarRef} data-fit={fit}>
            <header className="sidebar-header" style={{display: 'flex', justifyContent: 'center', paddingTop: 6}}>
                <NavLink to="/" className="brand" style={{display: 'flex', alignItems: 'center', gap: 2}}>
                    {/* Safari on iPhone and iPad sometimes left this logo blank: it decodes large images in the
                        background and then does not always repaint the sticky sidebar. The file is sized for the
                        sidebar and decoded with the page, so there is nothing to repaint afterwards. */}
                    <img
                        className="sidebar-logo"
                        src="/logo-wide-vodloft.png"
                        alt="VODLoft logo"
                        width={150}
                        height={78}
                        decoding="sync"
                        style={{borderRadius: 2, height: 'auto'}}
                    />
                </NavLink>
                {/* The footer links, shown here only when the footer itself is left out to make room. */}
                <Footer wrapperClass="sidebar-header-links" />
            </header>

            <div className="sidebar-inner" ref={innerRef}>
                <nav className="nav" aria-label="Primary" ref={navRef}>
                    <Navbar items={visibleNavItems(items)} />
                </nav>
            </div>
            <Footer wrapperClass="sidebar-footer" />
        </aside>
    )
}

function shows(item: NavItem): boolean {
    if (!item.access) return true
    if (typeof item.access === 'function') return item.access()
    const [area, level] = item.access
    return can(area, level ?? 'view')
}

export function visibleNavItems(navItems: NavItem[]): NavItem[] {
    return navItems.flatMap((item): NavItem[] => {
        if (!shows(item)) return []
        if (!item.children) return [item]
        const children = visibleNavItems(item.children)
        return children.length > 0 ? [{...item, children}] : []
    })
}
