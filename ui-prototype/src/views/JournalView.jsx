import { useState } from 'react'
import { Box, Group, Button, Paper, Text, Badge, Divider, Stack, SegmentedControl, Table, Loader, SimpleGrid, Tabs, Timeline } from '@mantine/core'
import { AreaChart, Heatmap } from '@mantine/charts'
import { ArrowsClockwise, Target } from '@phosphor-icons/react'
import { CARD } from '../constants'
import { useQueryClient } from '@tanstack/react-query'
import { useJournal, useTarget, useOverview, usePositionActions } from '../api/queries'
import CalendarHeatmap from '../components/CalendarHeatmap'
import { useT } from '../settings/i18n'

// центрированный спиннер для карточек (показывается только на первой загрузке)
function CardLoader({ h = 80, label }) {
  const t = useT()
  return (
    <Group justify="center" align="center" gap="xs" style={{ height: h }}>
      <Loader size="sm" /><Text size="xs" c="dimmed">{label || t('jrn.loading')}</Text>
    </Group>
  )
}

function EquityCurve({ data }) {
  return (
    <AreaChart h={150} data={data} dataKey="d" withDots={false} withXAxis={false}
      series={[{ name: 'pnl', label: 'PnL', color: 'red.5' }]} curveType="linear"
      gridAxis="y" yAxisProps={{ width: 52 }} valueFormatter={(v) => `$${v}`}
      fillOpacity={0.12} referenceLines={[{ y: 0, color: 'gray.5' }]} />
  )
}

const DAY_MS = 864e5
// divergent-палитра: убыток → нейтраль → профит (7 шагов, ноль ровно в середине)
const HEAT_COLORS = [
  'var(--mantine-color-red-9)',
  'var(--mantine-color-red-7)',
  'var(--mantine-color-red-4)',
  'light-dark(var(--mantine-color-gray-3), var(--mantine-color-dark-4))',
  'var(--mantine-color-teal-4)',
  'var(--mantine-color-teal-7)',
  'var(--mantine-color-teal-9)',
]
const fmtMoney = (v) => `${v < 0 ? '-' : '+'}$${Math.abs(v).toFixed(2)}`
const isoDate = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
// знак-корень: сжимает выбросы, разводит мелкие дни по палитре (для разреженных PnL лучше линейной шкалы)
const signSqrt = (v) => Math.sign(v) * Math.sqrt(Math.abs(v))

function PnlHeatmap({ data }) {
  const t = useT()
  const raw = data || {}
  // домен строим по трансформированным значениям, симметрично вокруг нуля
  const maxAbs = Math.max(1, ...Object.values(raw).map((v) => Math.abs(v)))
  const bound = signSqrt(maxAbs)
  // отдельный трансформированный объект для раскраски; оригинал (raw) остаётся для тултипа
  // clamp на [-bound, bound] — страховка, чтобы getHeatColor не вышел за границы палитры
  const heatData = Object.fromEntries(
    Object.entries(raw).map(([d, v]) => [d, Math.max(-bound, Math.min(bound, signSqrt(v)))])
  )
  const end = new Date()
  const start = new Date(end.getTime() - 364 * DAY_MS)
  return (
    <Box style={{ overflowX: 'auto' }}>
      <Heatmap
        data={heatData}
        startDate={isoDate(start)}
        endDate={isoDate(end)}
        domain={[-bound, bound]}
        colors={HEAT_COLORS}
        withMonthLabels
        withWeekdayLabels
        withTooltip
        getTooltipLabel={({ date }) => {
          const v = raw[date]
          return `${date} · ${v == null ? t('jrn.heatEmpty') : fmtMoney(v)}`
        }}
        rectSize={11}
        gap={3}
        rectRadius={2}
      />
      <Text size="xs" c="dimmed" mt={8}>{t('jrn.heatCaption')}</Text>
    </Box>
  )
}

const fmtHold = (m) => (m == null ? '—' : m < 90 ? `${m}м` : m < 2880 ? `${Math.round(m / 60)}ч` : `${Math.round(m / 1440)}д`)
const money0 = (v) => (v == null ? '—' : `${v >= 0 ? '+' : '−'}$${Math.abs(v).toLocaleString('en-US', { maximumFractionDigits: 0 })}`)

// Качество копирования: risk-метрики от биржевых закрытых сделок
function Analytics({ a }) {
  const t = useT()
  if (!a || !a.trades) return null
  const M = [
    [t('jrn.q.winrate'), a.winrate != null ? `${Math.round(a.winrate * 100)}%` : '—', `${a.wins}/${a.trades}`, undefined],
    [t('jrn.q.pf'), a.profit_factor != null ? a.profit_factor.toFixed(2) : '∞', t('jrn.q.pf.sub'), a.profit_factor == null || a.profit_factor >= 1 ? 'teal' : 'red'],
    [t('jrn.q.sharpe'), a.sharpe != null ? a.sharpe.toFixed(2) : '—', t('jrn.q.sharpe.sub'), undefined],
    [t('jrn.q.maxdd'), `−$${a.max_drawdown_usd.toLocaleString('en-US', { maximumFractionDigits: 0 })}`, t('jrn.q.maxdd.sub'), 'red'],
    [t('jrn.q.avghold'), fmtHold(a.avg_holding_min), t('jrn.q.avghold.sub'), undefined],
    [t('jrn.q.total'), money0(a.total_pnl), `${money0(a.best)} / ${money0(a.worst)}`, sgn(money0(a.total_pnl))],
  ]
  return (
    <>
      <Text fw={600} size="sm" mt="lg" mb={6}>{t('jrn.quality')}</Text>
      <Paper withBorder p="md" radius="md" style={CARD}>
        <SimpleGrid cols={{ base: 2, sm: 3, md: 6 }} spacing="lg" verticalSpacing="md">
          {M.map(([label, val, sub, color]) => (
            <Box key={label}>
              <Text fz={10} c="dimmed" tt="uppercase" style={{ letterSpacing: 0.4 }}>{label}</Text>
              <Text fw={700} size="lg" c={color} ff="monospace">{val}</Text>
              {sub && <Text fz={10} c="dimmed">{sub}</Text>}
            </Box>
          ))}
        </SimpleGrid>
      </Paper>
    </>
  )
}

function TargetBanner({ tg }) {
  const t = useT()
  if (!tg) return null
  return (
    <Paper withBorder p="sm" radius="md" mt="md" style={CARD}>
      <Group justify="space-between" wrap="nowrap">
        <Group gap="lg" wrap="nowrap">
          <Group gap={6} wrap="nowrap"><Target size={18} weight="fill" color="var(--mantine-color-blue-6)" /><Text size="xs" c="dimmed" tt="uppercase" fw={600}>{t('jrn.copying')}</Text></Group>
          <Box><Text fw={700} size="sm">{tg.name}</Text><Text fz={11} c="dimmed" ff="monospace">{tg.addr}</Text></Box>
          <Divider orientation="vertical" />
          <Box>
            <Text fz={10} c="dimmed" tt="uppercase">{t('jrn.leadPos')}</Text>
            <Group gap={5} wrap="nowrap"><Text size="sm" fw={600}>{tg.coin}</Text><Badge size="xs" color={tg.side === 'LONG' || tg.side === 'ЛОНГ' ? 'teal' : 'red'} variant="light">{tg.side}</Badge></Group>
          </Box>
          <Box><Text fz={10} c="dimmed" tt="uppercase">{t('jrn.ourRisk')}</Text><Text size="sm" fw={600}>{tg.risk} <Text span c="dimmed" fw={400}>· {t('jrn.lead')} {tg.leadRisk}</Text></Text></Box>
          <Box><Text fz={10} c="dimmed" tt="uppercase">{t('jrn.avg')}</Text><Text size="sm" fw={600}>{tg.avg} <Text span c="dimmed" fw={400}>≈ {t('jrn.lead')} {tg.leadAvg}</Text></Text></Box>
          {tg.live && <Badge color="red" variant="light" radius="sm">🔴 LIVE</Badge>}
        </Group>
      </Group>
    </Paper>
  )
}

// цвет по знаку денежной строки ('+$…' → teal, '−/-$…' → red, иначе нейтрально)
const sgn = (v) => { const s = String(v ?? ''); return s.startsWith('+') ? 'teal' : (s.startsWith('-') || s.startsWith('−')) ? 'red' : undefined }

function Overview({ o, loading }) {
  const t = useT()
  const OV = [
    [t('jrn.unreal'), o?.unreal, sgn(o?.unreal)], [t('jrn.leverage'), o?.leverage, undefined],
    [t('jrn.marginUse'), o?.marginUse, undefined], [t('jrn.yearPnl'), o?.yearPnl, sgn(o?.yearPnl)],
  ]
  return (
    <Paper withBorder p="md" radius="md" w={250} style={{ ...CARD, flexShrink: 0 }}>
      <Text fz={11} fw={700} c="dimmed" tt="uppercase" mb="sm" style={{ letterSpacing: 0.5 }}>{t('jrn.overview')}</Text>
      {loading ? <CardLoader h={120} /> : (
        <Stack gap="sm">
          {OV.map(([label, value, color]) => (
            <Group key={label} justify="space-between" wrap="nowrap"><Text fz={11} c="dimmed" tt="uppercase">{label}</Text><Text fw={700} c={color}>{value ?? '—'}</Text></Group>
          ))}
        </Stack>
      )}
    </Paper>
  )
}

function OpenPositions({ rows }) {
  const t = useT()
  const { close } = usePositionActions()
  const [busy, setBusy] = useState(null)   // sym позиции, которую сейчас закрываем
  const onClose = async (p) => {
    if (!window.confirm(`Закрыть позицию ${p.sym} (${p.side})? Рыночный ордер уйдёт на биржу.`)) return
    setBusy(p.sym)
    try {
      const r = await close({ symbol: p.sym, positionSide: p.positionSide })
      if (r?.error) window.alert(`Не удалось закрыть ${p.sym}: ${r.error}`)  // бэк вернул 200 {error}
    } catch (e) {
      window.alert(`Не удалось закрыть ${p.sym}: ${e?.message || e}`)       // сеть/401/HTTP-ошибка
    } finally {
      setBusy(null)
    }
  }
  return (
      <Paper withBorder radius="md" style={{ ...CARD, overflowX: 'auto' }}>
        <Table verticalSpacing="sm" horizontalSpacing="md" miw={1180}>
          <Table.Thead><Table.Tr style={{ fontSize: 11 }}>
            <Table.Th>{t('jrn.h.symbol')}</Table.Th>
            <Table.Th ta="right">{t('jrn.h.size')}</Table.Th><Table.Th ta="right">{t('jrn.h.entry')}</Table.Th><Table.Th ta="right">{t('jrn.h.breakeven')}</Table.Th>
            <Table.Th ta="right">{t('jrn.h.mark')}</Table.Th><Table.Th ta="right">{t('jrn.h.liq')}</Table.Th><Table.Th ta="right">{t('jrn.h.marginRatio')}</Table.Th>
            <Table.Th ta="right">{t('jrn.h.margin')}</Table.Th><Table.Th ta="right">{t('jrn.h.pnlRoi')}</Table.Th><Table.Th ta="right">{t('jrn.h.funding')}</Table.Th><Table.Th />
          </Table.Tr></Table.Thead>
          <Table.Tbody>
            {rows.map((p, i) => (
              <Table.Tr key={i}>
                <Table.Td>
                  <Text size="sm" fw={700}>{p.sym}</Text>
                  <Group gap={4} mt={3}>
                    <Badge size="xs" color="gray" variant="light">{p.perp}</Badge>
                    <Badge size="xs" color="gray" variant="light">{p.lev}</Badge>
                    <Badge size="xs" color={p.sideRaw === 'LONG' || p.side === 'ЛОНГ' ? 'teal' : 'red'} variant="light">{p.side}</Badge>
                  </Group>
                </Table.Td>
                <Table.Td ta="right"><Text size="sm" fw={600} c={p.sideRaw === 'LONG' || p.side === 'ЛОНГ' ? 'teal' : 'red'} ff="monospace">{p.size}</Text><Text fz={10} c="dimmed">{p.sizeUnit}</Text></Table.Td>
                <Table.Td ta="right"><Text size="sm" ff="monospace">{p.entry}</Text></Table.Td>
                <Table.Td ta="right"><Text size="sm" c="dimmed" ff="monospace">{p.breakeven}</Text></Table.Td>
                <Table.Td ta="right"><Text size="sm" ff="monospace">{p.mark}</Text></Table.Td>
                <Table.Td ta="right"><Text size="sm" c="orange" ff="monospace">{p.liq}</Text></Table.Td>
                <Table.Td ta="right"><Text size="sm" ff="monospace">{p.marginRatio}</Text></Table.Td>
                <Table.Td ta="right"><Text size="sm" ff="monospace">{p.margin}</Text><Text fz={10} c="dimmed">{p.marginType}</Text></Table.Td>
                <Table.Td ta="right"><Text size="sm" fw={600} c={(p.pnlPos ?? String(p.pnl).startsWith('+')) ? 'teal' : 'red'} ff="monospace">{p.pnl}</Text><Text fz={10} c={(p.pnlPos ?? String(p.pnl).startsWith('+')) ? 'teal' : 'red'}>{p.roi}</Text></Table.Td>
                <Table.Td ta="right"><Text size="sm" c="teal" ff="monospace">{p.funding}</Text><Text fz={10} c="dimmed">{p.fundingPct}</Text></Table.Td>
                <Table.Td><Button size="compact-xs" variant="light" color="red" loading={busy === p.sym} disabled={busy && busy !== p.sym} onClick={() => onClose(p)}>{t('jrn.h.close')}</Button></Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Paper>
  )
}

const fdatetime = (ms) => { if (!ms) return '—'; const d = new Date(ms); const p = (n) => String(n).padStart(2, '0'); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}` }
// ячейка «подпись / значение» в карточке закрытой позиции
function Field({ label, value, color }) {
  return (
    <Box>
      <Text fz={11} c="dimmed">{label}</Text>
      <Text fz={13} fw={500} c={color} ff="monospace">{value}</Text>
    </Box>
  )
}
// История позиций карточками (как на Binance): статус закрыто / частично закрыто
function ClosedPositions({ rows }) {
  const t = useT()
  return (
    <Stack gap="sm">
      {rows.map((p, i) => {
        const pos = (p.realizedPnl ?? 0) >= 0
        const partial = p.status === 'partial'
        return (
          <Paper key={i} withBorder p="md" radius="md" style={CARD}>
            <Group gap="xs" mb="sm" wrap="wrap">
              <Text fw={700} size="sm">{p.symbol}</Text>
              <Badge size="sm" radius="sm" color="gray" variant="light">{t('jrn.c.perp')}</Badge>
              <Badge size="sm" radius="sm" color={p.side === 'LONG' ? 'teal' : 'red'} variant="light">{p.side === 'LONG' ? t('tl.long') : t('tl.short')}</Badge>
              <Badge size="sm" radius="sm" color={p.bot ? 'blue' : 'gray'} variant="dot">{p.bot ? t('jrn.bot') : t('jrn.manual')}</Badge>
              <Text fz={13} fw={600} c={partial ? 'orange' : 'dimmed'} ml={4}>{partial ? t('jrn.c.partial') : t('jrn.c.full')}</Text>
            </Group>
            <SimpleGrid cols={{ base: 2, sm: 3, md: 5 }} spacing="md" verticalSpacing="sm">
              <Field label={t('jrn.c.opened')} value={fdatetime(p.open_time)} />
              <Field label={t('jrn.h.entry')} value={p.entry} />
              <Field label={t('jrn.c.maxsize')} value={p.max_qty ?? p.qty} />
              <Field label={t('jrn.c.pnlAfter')} value={money0(p.realizedPnl)} color={pos ? 'teal' : 'red'} />
              <Field label={t('jrn.c.closedAt')} value={fdatetime(p.close_time)} />
              <Field label={t('jrn.c.avgClose')} value={p.exit ?? '—'} />
              <Field label={t('jrn.c.volAfter')} value={p.qty} />
              <Field label={t('jrn.c.hold')} value={fmtHold(p.duration_min)} />
            </SimpleGrid>
          </Paper>
        )
      })}
    </Stack>
  )
}

// Лента событий (как «Последние записи» на Binance): открытие/закрытие лонга/шорта
const TL_LABEL = {
  'open-long': ['tl.openLong', 'teal'], 'open-short': ['tl.openShort', 'red'],
  'close-long': ['tl.closeLong', 'red'], 'close-short': ['tl.closeShort', 'teal'],
}
function TradesTimeline({ rows }) {
  const t = useT()
  return (
    <Paper withBorder radius="md" p="lg" style={CARD}>
      <Timeline active={rows.length} bulletSize={12} lineWidth={2} color="gray">
        {rows.map((r, i) => {
          const [labelKey, color] = TL_LABEL[r.action] || ['tl.trade', 'gray']
          const verb = r.action?.startsWith('open') ? t('tl.open') : t('tl.close')
          const pos = r.action?.includes('long') ? t('tl.long') : t('tl.short')
          return (
            <Timeline.Item key={i} lineVariant={i === rows.length - 1 ? 'dashed' : 'solid'}
              bullet={<Box w={8} h={8} style={{ borderRadius: '50%', background: `var(--mantine-color-${color}-6)` }} />}
              title={<Group gap="sm" wrap="nowrap">
                <Text fz={12} c="dimmed" ff="monospace">{r.dtFull}</Text>
                <Badge size="sm" radius="sm" color={color} variant="light">{t(labelKey)}</Badge>
                {r.bot && <Badge size="xs" color="blue" variant="dot">{t('jrn.bot')}</Badge>}
              </Group>}>
              <Text fz={13} c="dimmed" mt={2}>
                {verb} {pos}-{t('tl.pos')} <Text span fw={600} c="var(--mantine-color-text)">{r.sym}</Text> {t('tl.byPrice')} <b>{r.priceRaw}</b>, {t('tl.vol')} <b>{r.qty}</b> {t('tl.total')} <b>${Math.round(r.notional).toLocaleString('en-US')}</b>
                {r.pnlRaw !== 0 && <>. {t('tl.pnl')}: <Text span fw={600} c={r.pnlRaw >= 0 ? 'teal' : 'red'}>{r.pnl}</Text></>}
              </Text>
            </Timeline.Item>
          )
        })}
      </Timeline>
    </Paper>
  )
}

export default function JournalView() {
  const [view, setView] = useState('curve')
  const t = useT()
  const qc = useQueryClient()
  const { data: journal, isLoading: journalLoading } = useJournal()
  const { data: target } = useTarget()
  const { data: overview, isLoading: overviewLoading } = useOverview()
  const refresh = () => ['journal', 'target', 'overview'].forEach((k) => qc.invalidateQueries({ queryKey: [k] }))
  return (
    <Box p="lg" maw={1500} mx="auto">
      <Group justify="flex-end" mb="xs">
        <Button size="xs" variant="default" leftSection={<ArrowsClockwise size={14} />} onClick={refresh}>{t('jrn.refresh')}</Button>
      </Group>

      <TargetBanner tg={target} />

      <Group align="stretch" gap="md" mt="md" wrap="nowrap">
        <Overview o={overview} loading={overviewLoading} />
        <Paper withBorder p="md" radius="md" style={{ ...CARD, flex: 1, minWidth: 0 }}>
          <Group justify="space-between" mb="sm" wrap="nowrap">
            <Group gap="sm" wrap="nowrap">
              <Text fw={600} size="sm">{t('jrn.realized')}</Text>
              <Text fw={700} c={sgn(overview?.realized)}>{overview?.realized ?? '—'}</Text>
              {overview?.realizedPct && overview.realizedPct !== '—' && (
                <Badge color={sgn(overview?.realized)} size="sm" radius="sm" variant="light">{overview.realizedPct}</Badge>
              )}
            </Group>
            <SegmentedControl size="xs" value={view} onChange={setView}
              data={[{ value: 'curve', label: t('jrn.curve') }, { value: 'map', label: t('jrn.map') }]} />
          </Group>
          <Box style={{ minHeight: 152 }}>
            {journalLoading ? <CardLoader h={150} /> : journal && (view === 'curve' ? <EquityCurve data={journal.curve} /> : <PnlHeatmap data={journal.heat} />)}
          </Box>
        </Paper>
      </Group>

      {!journalLoading && <Analytics a={journal?.analytics} />}

      <Tabs defaultValue="open" mt="lg" keepMounted={false}>
        <Tabs.List>
          <Tabs.Tab value="open">{t('jrn.openPos')}{journal?.open?.length ? ` (${journal.open.length})` : ''}</Tabs.Tab>
          <Tabs.Tab value="history">{t('jrn.closedPos')}{journal?.closed?.length ? ` (${journal.closed.length})` : ''}</Tabs.Tab>
          <Tabs.Tab value="trades">{t('jrn.trades')}</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="open" pt="md">
          {journalLoading ? <CardLoader h={100} />
            : journal?.open?.length ? <OpenPositions rows={journal.open} />
              : <Paper withBorder radius="md" style={CARD}><Text size="sm" c="dimmed" p="md">{t('jrn.noOpen')}</Text></Paper>}
        </Tabs.Panel>
        <Tabs.Panel value="history" pt="md">
          {journalLoading ? <CardLoader h={100} />
            : journal?.closed?.length ? <ClosedPositions rows={journal.closed} />
              : <Paper withBorder radius="md" style={CARD}><Text size="sm" c="dimmed" p="md">{t('jrn.noClosed')}</Text></Paper>}
        </Tabs.Panel>
        <Tabs.Panel value="trades" pt="md">
          {journalLoading ? <CardLoader h={100} />
            : journal?.trades?.length ? <TradesTimeline rows={journal.trades} />
              : <Paper withBorder radius="md" style={CARD}><Text size="sm" c="dimmed" p="md">{t('jrn.noTrades')}</Text></Paper>}
        </Tabs.Panel>
      </Tabs>
    </Box>
  )
}
