import { Key, SlidersHorizontal, Bell, Palette, Lock } from '@phosphor-icons/react'

// единый стиль карточек (чёткий бордер). light-dark — чтобы в тёмной теме
// бордер брался из родного токена Mantine (dark-4), а не из светлого gray-4
// Реф-ссылка/код Binance — «поддержать автора»: автор получает долю комиссии БИРЖИ,
// средства юзера не трогаются. Форк может заменить на свой код.
export const REFERRAL_CODE = '718442076'
export const REFERRAL_URL = 'https://www.binance.com/register?ref=718442076'

export const CARD = { borderColor: 'light-dark(var(--mantine-color-gray-4), var(--mantine-color-dark-4))', borderWidth: 1.5 }
// мягкий фон вложенной карточки (как dark-8 у боевого) и тонкая линия-разделитель
export const SUBTLE_BG = 'light-dark(var(--mantine-color-gray-1), var(--mantine-color-dark-6))'
export const HAIRLINE = 'light-dark(var(--mantine-color-gray-2), var(--mantine-color-dark-4))'
// навигационный хром: неактивный текст и активный чип (blue-light сам адаптируется к теме)
export const NAV_INACTIVE = 'light-dark(var(--mantine-color-gray-7), var(--mantine-color-gray-5))'
export const ACTIVE_BG = 'var(--mantine-color-blue-light)'
export const ACTIVE_FG = 'var(--mantine-color-blue-light-color)'
// единая ширина колонки контролов в настройках
export const CW = 130

// верхние табы (Настройки/Логи — через иконки в шапке, не тут)
export const TABS = [
  { value: 'journal', label: 'Журнал' },
  { value: 'monitor', label: 'Монитор' },
]

// секции настроек
export const SECTIONS = [
  { value: 'keys', label: 'Счета / API-ключи', icon: Key },
  { value: 'params', label: 'Параметры торговли', icon: SlidersHorizontal },
  { value: 'alerts', label: 'Уведомления', icon: Bell },
  { value: 'ui', label: 'Интерфейс', icon: Palette },
  { value: 'access', label: 'Доступ', icon: Lock },
]

// светофор сервисов
export const SVC_COLOR = { ok: 'teal', warn: 'yellow', down: 'red', off: 'gray' }
export const SVC_LABEL = { ok: 'ok', warn: 'задержка', down: 'нет связи', off: 'выкл' }

// уровни логов
export const LVL = {
  hb: { tag: 'НВ', color: 'gray' },
  trade: { tag: 'КОП', color: 'teal' },
  monitor: { tag: 'МОН', color: 'blue' },
  target: { tag: 'ЦЕЛЬ', color: 'grape' },
  skip: { tag: 'ПРОП', color: 'orange' },
  error: { tag: 'ОШ', color: 'red' },
  info: { tag: 'ИНФ', color: 'gray' },
}
export const LOG_FILTERS = [
  { value: 'all', label: 'Всё' },
  { value: 'monitor', label: 'Монитор' },
  { value: 'target', label: 'Активность цели' },
  { value: 'trade', label: 'Сделки' },
  { value: 'skip', label: 'Пропуски' },
  { value: 'error', label: 'Ошибки' },
]

// типы счетов
export const TYPE_META = {
  futures: { label: 'фьючерсы', color: 'gray' },
  copy: { label: 'копи-портфель', color: 'grape' },
  spot: { label: 'спот', color: 'cyan' },
}

// ключи-параметры счёта (оверрайды активного) — 1:1 с PER_ACCOUNT на бэке (server/controller.py).
// Остальное (poll/data_mode/анти-спам/telegram/accounts/active_account) — глобальное (top-level).
export const PER_ACCOUNT_KEYS = new Set([
  'targets', 'execution_mode', 'leverage_mode', 'fixed_leverage', 'mirror_max_leverage',
  'leverage_cap', 'max_notional_per_coin_usd', 'coin_whitelist', 'favorability_gate',
  'favorability_tol_pct', 'auto_sync', 'manage_only_bot_positions', 'start_skip_open',
  'start_skip_profit_pct', 'maker_wait_sec', 'maker_max_chases', 'maker_fallback_taker',
])
