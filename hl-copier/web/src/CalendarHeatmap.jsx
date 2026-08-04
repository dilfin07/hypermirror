import { Tooltip } from '@mantine/core'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const isoUTC = (dt) => dt.toISOString().slice(0, 10)
const money = (v) =>
  v == null ? 'нет сделок' : `${v >= 0 ? '+' : '-'}$${Math.abs(v).toLocaleString('en-US', { maximumFractionDigits: 2 })}`

// Календарь дневного PnL: зелёный — плюс, красный — минус, интенсивность по модулю.
// Тянется на всю ширину контейнера (колонки flex, ячейки — квадраты).
export default function CalendarHeatmap({ data = {}, days = 364, gap = 3 }) {
  const today = new Date()
  today.setUTCHours(0, 0, 0, 0)
  const start = new Date(today)
  start.setUTCDate(today.getUTCDate() - days)
  start.setUTCDate(start.getUTCDate() - start.getUTCDay()) // выровнять на воскресенье

  let maxAbs = 0
  Object.values(data).forEach((v) => { if (Math.abs(v) > maxAbs) maxAbs = Math.abs(v) })

  const cells = []
  for (const d = new Date(start); d <= today; d.setUTCDate(d.getUTCDate() + 1)) {
    const key = isoUTC(d)
    cells.push({ key, value: key in data ? data[key] : null, month: d.getUTCMonth() })
  }
  const weeks = []
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7))

  const color = (v) => {
    if (v == null) return 'var(--mantine-color-dark-5)'
    if (v === 0) return 'var(--mantine-color-dark-4)'
    const a = 0.35 + 0.65 * Math.min(1, Math.abs(v) / (maxAbs || 1))
    return v > 0 ? `rgba(47,158,68,${a})` : `rgba(224,49,49,${a})`
  }

  return (
    <div style={{ display: 'flex', gap, width: '100%' }}>
      {weeks.map((w, wi) => {
        const showMonth = wi === 0 || w[0].month !== weeks[wi - 1][0].month
        return (
          <div key={wi} style={{ display: 'flex', flexDirection: 'column', gap, flex: 1, minWidth: 0 }}>
            <div style={{ height: 12, fontSize: 9, color: 'var(--mantine-color-dimmed)', whiteSpace: 'nowrap' }}>
              {showMonth ? MONTHS[w[0].month] : ''}
            </div>
            {w.map((c) => (
              <Tooltip key={c.key} label={`${c.key}: ${money(c.value)}`} withArrow openDelay={0} fz="xs">
                <div style={{ width: '100%', aspectRatio: '1 / 1', borderRadius: 2, background: color(c.value) }} />
              </Tooltip>
            ))}
          </div>
        )
      })}
    </div>
  )
}
