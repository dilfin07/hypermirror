const token = () => localStorage.getItem('hlc_token') || ''
export const setToken = (t) => (t ? localStorage.setItem('hlc_token', t) : localStorage.removeItem('hlc_token'))

async function j(url, opts = {}) {
  const headers = { ...(opts.headers || {}) }
  const t = token()
  if (t) headers.Authorization = 'Bearer ' + t
  const r = await fetch(url, { ...opts, headers })
  if (r.status === 401) {
    setToken('')
    window.dispatchEvent(new Event('hlc-unauth'))
  }
  return r.json()
}
const jpost = (path, body) =>
  j('/api' + path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) })

export const getStatus = () => j('/api/status')
export const getLogs = () => j('/api/logs')
export const getConfig = () => j('/api/config')
export const getAccountStats = () => j('/api/account_stats')
export const getKlines = (symbol, interval, limit = 300) =>
  j(`/api/klines?symbol=${symbol}&interval=${interval}&limit=${limit}`)
export const getTrades = (symbol) => j(`/api/trades?symbol=${symbol}`)
export const getMonitors = () => j('/api/monitors')
export const getCopySessions = () => j('/api/copy_sessions')
export const authStatus = () => j('/api/auth_status')
export const login = (password) => jpost('/login', { password })
export const post = jpost
