import { api as mockApi } from './mockClient'
import { api as liveApi } from './liveClient'

// Селектор источника данных. VITE_API=live → реальный бэкенд (Pi через прокси),
// иначе моки. Хуки (queries.js) импортируют api отсюда и не знают о режиме.
export const MODE = import.meta.env.VITE_API === 'live' ? 'live' : 'mock'
export const api = MODE === 'live' ? liveApi : mockApi
