import {NavLink} from 'react-router-dom'
import Footer from './Footer'
import Navbar from './Navbar'
import type { NavItem } from './navTypes'
import {faIcon} from '../../icons/faIcon'
const items: NavItem[] = [
    {path: '/', label: 'Home', icon: faIcon('fas', 'house')},
    {path: '/discover', label: 'Discover / Add', icon: faIcon('fas', 'magnifying-glass')},
    {path: '/library', label: 'Library', icon: faIcon('fas', 'book-open')},
    {path: '/management', label: 'Management', icon: faIcon('fas', 'layer-group')},
    {path: '/tasks', label: 'Tasks', icon: faIcon('fas', 'clipboard-list')},
    {path: '/logs', label: 'Logs', icon: faIcon('fas', 'file-lines')},
    {path: '/settings', label: 'Settings', icon: faIcon('fas', 'gear')},
]

export default function Sidebar() {

    return (
        <aside className="sidebar" aria-label="Sidebar">
            <header className="sidebar-header" style={{display: 'flex', justifyContent: 'center', paddingTop: 6}}>
                <NavLink to="/" className="brand" style={{display: 'flex', alignItems: 'center', gap: 2}}>
                    <span style={{fontSize: 25, fontWeight: 750, padding: '12px 0'}}>VodLoft</span>
                </NavLink>
            </header>

            <div className="sidebar-inner">
                <nav className="nav" aria-label="Primary">
                    <Navbar items={items} />
                </nav>
            </div>
            <Footer wrapperClass="sidebar-footer" />
        </aside>
    )
}
