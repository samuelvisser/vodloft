import {NavLink} from 'react-router-dom'
import {library} from '@fortawesome/fontawesome-svg-core'
import {fas} from '@awesome.me/kit-83fa1ac5a9/icons'
import Footer from './Footer'
import Navbar from './Navbar'
import type { NavItem } from './navTypes'

// Register the kit's solid icon pack so we can reference icons by [prefix, name]
library.add(fas)

const items: NavItem[] = [
    {path: '/', label: 'Home', icon: ['fas', 'house']},
    {path: '/discover', label: 'Discover / Add', icon: ['fas', 'magnifying-glass']},
    {path: '/library', label: 'Library', icon: ['fas', 'book-open']},
    {path: '/management', label: 'Management', icon: ['fas', 'layer-group']},
    {path: '/settings', label: 'Settings', icon: ['fas', 'gear']},
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
