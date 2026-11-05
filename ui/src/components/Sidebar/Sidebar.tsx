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

export default function Sidebar() {

    return (
        <aside className="sidebar" aria-label="Sidebar">
            <header className="sidebar-header" style={{display: 'flex', justifyContent: 'center', paddingTop: 6}}>
                <NavLink to="/" className="brand" style={{display: 'flex', alignItems: 'center', gap: 2}}>
                    {/* Safari on iPhone and iPad sometimes left this logo blank: it decodes large images in the
                        background and then does not always repaint the sticky sidebar. The file is sized for the
                        sidebar and decoded with the page, so there is nothing to repaint afterwards. */}
                    <img
                        src="/logo-wide-vodloft.png"
                        alt="VODLoft logo"
                        width={150}
                        height={78}
                        decoding="sync"
                        style={{borderRadius: 2, height: 'auto'}}
                    />
                </NavLink>
            </header>

            <div className="sidebar-inner">
                <nav className="nav" aria-label="Primary">
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
