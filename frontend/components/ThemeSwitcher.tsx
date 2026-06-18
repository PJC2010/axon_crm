'use client'

import { useEffect, useState } from 'react'

/* Blueprint accent palettes — must match the .lp-root[data-theme=...]
   blocks in app/landing.css. The swatch is the bright (step-4) accent. */
const THEMES = [
  { id: 'cobalt', label: 'Cobalt', swatch: '#4c90f0' },
  { id: 'indigo', label: 'Indigo', swatch: '#9881f3' },
  { id: 'turquoise', label: 'Turquoise', swatch: '#13c9ba' },
  { id: 'cerulean', label: 'Cerulean', swatch: '#3fa6da' },
  { id: 'violet', label: 'Violet', swatch: '#bd6bbd' },
  { id: 'rose', label: 'Rose', swatch: '#f5498b' },
] as const

const STORAGE_KEY = 'lp-theme'
const DEFAULT_THEME = 'cobalt'

function applyTheme(id: string) {
  document.querySelector('.lp-root')?.setAttribute('data-theme', id)
}

export default function ThemeSwitcher() {
  const [active, setActive] = useState<string>(DEFAULT_THEME)

  // Restore the previously chosen palette on mount.
  useEffect(() => {
    const saved = localStorage.getItem(STORAGE_KEY) ?? DEFAULT_THEME
    setActive(saved)
    applyTheme(saved)
  }, [])

  function select(id: string) {
    setActive(id)
    applyTheme(id)
    localStorage.setItem(STORAGE_KEY, id)
  }

  return (
    <div className="lp-theme-switcher" role="group" aria-label="Preview accent palette">
      <span className="lp-theme-switcher-label">Preview palette</span>
      <div className="lp-theme-swatches">
        {THEMES.map((theme) => (
          <button
            key={theme.id}
            type="button"
            className="lp-theme-swatch"
            style={{ background: theme.swatch }}
            aria-label={theme.label}
            aria-pressed={active === theme.id}
            title={theme.label}
            onClick={() => select(theme.id)}
          />
        ))}
      </div>
    </div>
  )
}
