import { MOCK } from './mock'
import { PER_ACCOUNT_KEYS } from '../constants'

// «Сервер» на моках: состояние в памяти, мутации меняют его (имитация бэка).
// Используется в режиме VITE_API=mock (по умолчанию) и как фолбэк для ещё не
// перенесённых на live экранов (см. liveClient.js).
const db = structuredClone(MOCK)
const delay = (ms) => new Promise((r) => setTimeout(r, ms))

const get = async (key) => { await delay(120); return structuredClone(db[key]) }
const mutate = async (fn) => { await delay(80); fn(db); return true }

// активный счёт + его оверрайды (как на бэке: defaults ⊕ overrides активного)
const activeAcct = () => {
  const aid = db.config.active_account || 'main'
  return aid !== 'main' ? (db.config.accounts || []).find((a) => a.id === aid) : null
}
const effectiveConfig = () => {
  const acct = activeAcct()
  return { ...db.config, ...((acct && acct.overrides) || {}) }
}

// карточная форма счёта из config.accounts
const accCard = (a) => ({ id: a.id, label: a.label || a.id, type: a.type || 'futures', network: a.network || 'mainnet', key_env: a.key_env || 'BINANCE', balance: a.id === 'main' ? db.balance : '—', hasKeys: a.id === 'main',
  lastActive: a.last_active ?? Math.floor(Date.now() / 1000) - (a.id === 'main' ? 180 : 3 * 86400) }) // демо: main «только что», copy «3 дн»

export const api = {
  // чтение
  services: () => get('services'),
  logs: () => get('logs'),
  monitors: () => get('monitors'),
  target: () => get('target'),
  overview: () => get('overview'),
  journal: () => get('journal'),
  accounts: async () => { await delay(120); return (db.config.accounts || []).map(accCard) },
  meta: async () => { await delay(120); return { balance: db.balance, activeAccount: db.config.active_account } },
  config: async () => { await delay(120); return structuredClone(effectiveConfig()) },

  // мутации — монитор
  toggleMonitor: (id, field) => mutate((d) => { const m = d.monitors.find((x) => x.id === id); if (m) m[field] = !m[field] }),
  removeMonitor: (id) => mutate((d) => { d.monitors = d.monitors.filter((x) => x.id !== id) }),
  addMonitor: (rec) => mutate((d) => { d.monitors = [rec, ...d.monitors] }),
  // цель копирования: единственная (set → только этот copying, clear → все off)
  setCopyTarget: (addr) => mutate((d) => { d.monitors.forEach((x) => { x.copying = x.addr === addr || x.id === addr }) }),
  clearCopyTarget: () => mutate((d) => { d.monitors.forEach((x) => { x.copying = false }) }),

  // мутации — счета/активный (config)
  setActiveAccount: (id) => mutate((d) => { d.config.active_account = id }),
  switchActive: (id) => mutate((d) => { d.config.active_account = id }),
  // действия бота (за подтверждением модалки смены счёта)
  stopBot: () => mutate(() => {}),
  closePosition: ({ symbol }) => mutate((d) => { d.journal.open = (d.journal.open || []).filter((p) => p.sym !== symbol) }),
  deleteAccount: (id) => mutate((d) => { d.config.accounts = d.config.accounts.filter((a) => a.id !== id); if (d.config.active_account === id) d.config.active_account = 'main' }),
  addAccountKeys: ({ account }) => mutate((d) => { d.config.accounts = [...d.config.accounts.filter((a) => a.id !== account.id), account] }),

  // мутации — настройки: per-account ключи активного счёта → в его overrides, остальное → top-level (как на бэке)
  saveConfig: (cfg) => mutate((d) => {
    const aid = d.config.active_account || 'main'
    const acct = aid !== 'main' ? (d.config.accounts || []).find((a) => a.id === aid) : null
    const ov = acct ? (acct.overrides = acct.overrides || {}) : null
    for (const [k, v] of Object.entries(cfg)) {
      if (k === 'accounts' || k === 'active_account') continue
      if (PER_ACCOUNT_KEYS.has(k) && ov) ov[k] = v
      else d.config[k] = v
    }
  }),
  saveTelegram: ({ chat_id, enabled, token }) => mutate((d) => { d.config.telegram = { ...d.config.telegram, chat_id, enabled, has_token: token ? true : d.config.telegram.has_token } }),
  testTelegram: async () => { await delay(400); return { ok: true } },
  saveAuth: ({ enabled, password }) => mutate((d) => { d.config.auth_enabled = enabled; if (password) d.config.has_ui_password = true }),
}
