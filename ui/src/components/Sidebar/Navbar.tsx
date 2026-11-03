import { NavLink } from 'react-router-dom'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import type { NavItem, NavSubmenu } from './navTypes'
import Submenu from './Submenu'

export type NavbarProps = {
  items: NavItem[]
}

export default function Navbar({ items }: NavbarProps) {
  return (
    <>
      {items.map((item) => {
        if ('children' in item) {
          const submenu = item as NavSubmenu
          return (
            <Submenu key={submenu.label} label={submenu.label} icon={submenu.icon} items={submenu.children} />
          )
        }
        const IconOverlay = item.iconOverlay
        return (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.end}
            className={({ isActive }) => 'nav-item' + (isActive ? ' active' : '')}
          >
            <span className="icon" aria-hidden>
              <FontAwesomeIcon icon={item.icon} />
              {IconOverlay && <IconOverlay />}
            </span>
            <span>{item.label}</span>
          </NavLink>
        )
      })}
    </>
  )
}
