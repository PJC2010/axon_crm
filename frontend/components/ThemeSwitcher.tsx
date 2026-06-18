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

/* Page-canvas colors from Blueprint's dark-gray ramp. */
const BACKGROUNDS = [
  { id: 'dark-gray', label: 'Dark Gray', swatch: '#1c2127' },
  { id: 'black', label: 'Black', swatch: '#111418' },
  { id: 'slate', label: 'Slate', swatch: '#252a31' },
] as const

/* Canvas textures — map to the .lp-tex-swatch.* preview classes. */
const TEXTURES = [
  { id: 'none', label: 'Flat' },
  { id: 'dots', label: 'Dots' },
  { id: 'grid', label: 'Grid' },
  { id: 'diagonal', label: 'Diagonal' },
  { id: 'grain', label: 'Grain' },
  { id: 'crosshatch', label: 'Crosshatch' },
  { id: 'weave', label: 'Weave' },
  { id: 'rings', label: 'Rings' },
  { id: 'zigzag', label: 'Zigzag' },
  { id: 'carbon', label: 'Carbon' },
] as const

const SETTINGS = {
  theme: { attr: 'data-theme', key: 'lp-theme', fallback: 'cobalt' },
  bg: { attr: 'data-bg', key: 'lp-bg', fallback: 'dark-gray' },
  texture: { attr: 'data-texture', key: 'lp-texture', fallback: 'none' },
} as const

type SettingName = keyof typeof SETTINGS

function apply(name: SettingName, value: string) {
  document.querySelector('.lp-root')?.setAttribute(SETTINGS[name].attr, value)
}

export default function ThemeSwitcher() {
  const [theme, setTheme] = useState<string>(SETTINGS.theme.fallback)
  const [bg, setBg] = useState<string>(SETTINGS.bg.fallback)
  const [texture, setTexture] = useState<string>(SETTINGS.texture.fallback)

  // Restore saved selections on mount.
  useEffect(() => {
    const restore = (name: SettingName, set: (v: string) => void) => {
      const value = localStorage.getItem(SETTINGS[name].key) ?? SETTINGS[name].fallback
      set(value)
      apply(name, value)
    }
    restore('theme', setTheme)
    restore('bg', setBg)
    restore('texture', setTexture)
  }, [])

  const select = (name: SettingName, set: (v: string) => void, value: string) => {
    set(value)
    apply(name, value)
    localStorage.setItem(SETTINGS[name].key, value)
  }

  return (
    <div className="lp-theme-switcher" role="group" aria-label="Design system preview controls">
      <div className="lp-switch-group">
        <span className="lp-theme-switcher-label">Accent</span>
        <div className="lp-theme-swatches">
          {THEMES.map((t) => (
            <button
              key={t.id}
              type="button"
              className="lp-theme-swatch"
              style={{ background: t.swatch }}
              aria-label={t.label}
              aria-pressed={theme === t.id}
              title={t.label}
              onClick={() => select('theme', setTheme, t.id)}
            />
          ))}
        </div>
      </div>

      <div className="lp-switch-group">
        <span className="lp-theme-switcher-label">Background</span>
        <div className="lp-theme-swatches">
          {BACKGROUNDS.map((b) => (
            <button
              key={b.id}
              type="button"
              className="lp-theme-swatch lp-bg-swatch"
              style={{ background: b.swatch }}
              aria-label={b.label}
              aria-pressed={bg === b.id}
              title={b.label}
              onClick={() => select('bg', setBg, b.id)}
            />
          ))}
        </div>
      </div>

      <div className="lp-switch-group">
        <span className="lp-theme-switcher-label">Texture</span>
        <div className="lp-theme-swatches">
          {TEXTURES.map((tx) => (
            <button
              key={tx.id}
              type="button"
              className={`lp-tex-swatch ${tx.id}`}
              aria-label={tx.label}
              aria-pressed={texture === tx.id}
              title={tx.label}
              onClick={() => select('texture', setTexture, tx.id)}
            />
          ))}
        </div>
      </div>
    </div>
  )
}
