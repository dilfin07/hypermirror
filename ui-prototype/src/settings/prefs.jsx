import { createContext, useContext, useState } from 'react'

// Пользовательские настройки интерфейса (масштаб/язык/пояс) с сохранением в localStorage.
// Тема (light/dark) живёт отдельно — ей управляет Mantine (useMantineColorScheme).
const KEY = 'hlc.prefs'
const load = () => { try { return JSON.parse(localStorage.getItem(KEY)) || {} } catch { return {} } }
const save = (next) => { try { localStorage.setItem(KEY, JSON.stringify(next)) } catch { /* приватный режим */ } }

const DEFAULTS = { scale: 0.9, lang: 'ru', tz: 'utc' }

const PrefsCtx = createContext(null)

export function PrefsProvider({ children }) {
  const [prefs, setPrefs] = useState(() => ({ ...DEFAULTS, ...load() }))
  const set = (patch) => setPrefs((p) => { const next = { ...p, ...patch }; save(next); return next })
  const value = {
    ...prefs,
    setScale: (scale) => set({ scale }),
    setLang: (lang) => set({ lang }),
    setTz: (tz) => set({ tz }),
  }
  return <PrefsCtx.Provider value={value}>{children}</PrefsCtx.Provider>
}

export const usePrefs = () => useContext(PrefsCtx)
