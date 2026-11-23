import type { ComponentType } from 'react'
import type { IconProp } from '@fortawesome/fontawesome-svg-core'
import type { Area, Level } from '../../lib/access'

export type BaseNav = {
  label: string
  icon: IconProp
  /** Shown only to people with at least this level; a submenu also hides when none of its items show. */
  access?: [Area, Level?] | ((context: NavContext) => boolean)
}

/** What decides whether some items show, besides the person's access. */
export type NavContext = {
  /** A Source with a catalogue to browse has an added Site, such as The Daily Wire. */
  browsable: boolean
}

export type NavLinkItem = BaseNav & {
  path: string
  end?: boolean
  /** Drawn over the icon, for a live marker such as running downloads. */
  iconOverlay?: ComponentType
  children?: never
}

export type NavSubmenu = BaseNav & {
  children: NavItem[]
  path?: never
}

export type NavItem = NavLinkItem | NavSubmenu
