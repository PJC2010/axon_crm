import {
  Home, Users, Kanban, Map as MapIcon, CheckSquare, Receipt, BookOpen, Phone,
  PhoneOutgoing, type LucideIcon,
} from 'lucide-react'
import type { ModuleKey } from './types'

/**
 * Single source of truth for the app's primary feature navigation.
 *
 * Each destination optionally declares the feature module(s) it belongs to. An
 * item with no `modules` is part of `core` and is always shown. An item with
 * `modules` is shown only when the account has at least one of them enabled
 * (see useEntitlements + isNavVisible), so pricing plans can hide locked features
 * from the nav. Settings/sign-out are intentionally not here — they are always
 * available and rendered separately in each header.
 */
export interface NavItem {
  href: string
  label: string
  /** Compact label for the dense desktop header (falls back to `label`). */
  shortLabel?: string
  icon: LucideIcon
  /** Visible when ANY listed module is enabled. Omit for always-on core items. */
  modules?: ModuleKey[]
  /** Terminology key — when set, the label is translated per business type. */
  termKey?: string
}

export const NAV_ITEMS: NavItem[] = [
  { href: '/home',        label: 'Home',        icon: Home },
  { href: '/dashboard',   label: 'Leads',       icon: Users, termKey: 'leads' },
  { href: '/pipeline',    label: 'Pipeline',    icon: Kanban },
  { href: '/map',         label: 'Map',         icon: MapIcon,  modules: ['map'] },
  { href: '/tasks',       label: 'Tasks',       icon: CheckSquare },
  { href: '/calls',       label: 'Calls',       icon: Phone,    modules: ['calls'] },
  { href: '/dialer',      label: 'Dialer',      icon: PhoneOutgoing, modules: ['calls'] },
  { href: '/expenses',    label: 'Expenses',    icon: Receipt,  modules: ['bookkeeping'] },
  // The Bookkeeping hub surfaces P&L, invoices/AR, and quotes — show it if any
  // of those modules is enabled.
  { href: '/bookkeeping', label: 'Bookkeeping', shortLabel: 'Books', icon: BookOpen,
    modules: ['bookkeeping', 'invoicing', 'quotes'] },
]

/** Whether a nav item should be shown given the account's enabled modules. */
export function isNavVisible(item: NavItem, hasModule: (m: ModuleKey) => boolean): boolean {
  return !item.modules || item.modules.some(hasModule)
}
