import { useEffect, useState } from 'react'
import { Card, Tabs, Badge, Text, Group, Stack, Anchor, Table, Collapse, SimpleGrid } from '@mantine/core'
import { getCopySessions } from '../api'

const dt = (s) => (s ? new Date(s).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—')
const num = (x, d = 2) => (x == null ? '—' : Number(x).toLocaleString('en-US', { maximumFractionDigits: d, minimumFractionDigits: d }))
const Pnl = ({ v, pre = '$' }) => v == null ? <Text span c="dimmed">—</Text>
  : <Text span ff="monospace" c={v >= 0 ? 'teal' : 'red'}>{v >= 0 ? '+' : '−'}{pre}{num(Math.abs(v))}</Text>

const REASON = { stopped: 'Остановка копирования', target_changed: 'Смена цели', cleared: 'Цель убрана',
  panic: '🚨 PANIC', superseded: 'Перезапуск', 'прервано (реконстр.)': 'Прервано' }

function Metric({ label, children }) {
  return <div><Text size="xs" c="dimmed">{label}</Text><Text size="sm" fw={600}>{children}</Text></div>
}

function Positions({ rows }) {
  if (!rows?.length) return null
  return (
    <Table fz="xs" verticalSpacing={3} mt="xs">
      <Table.Thead><Table.Tr c="dimmed">
        <Table.Th>Монета</Table.Th><Table.Th>Сторона</Table.Th>
        <Table.Th ta="right">Размер</Table.Th><Table.Th ta="right">Вход</Table.Th><Table.Th ta="right">uPnL</Table.Th>
      </Table.Tr></Table.Thead>
      <Table.Tbody>{rows.map((p, i) => (
        <Table.Tr key={i}>
          <Table.Td fw={600}>{p.coin}</Table.Td>
          <Table.Td><Badge size="xs" color={p.side === 'SHORT' ? 'red' : 'teal'}>{p.side}</Badge></Table.Td>
          <Table.Td ta="right" ff="monospace">{num(p.qty, 4)}</Table.Td>
          <Table.Td ta="right" ff="monospace">{num(p.entry, 4)}</Table.Td>
          <Table.Td ta="right"><Pnl v={p.uPnl} /></Table.Td>
        </Table.Tr>))}</Table.Tbody>
    </Table>
  )
}

function SessionCard({ s }) {
  const [open, setOpen] = useState(false)
  const paper = s.paper
  const live = !paper
  const realized = paper ? s.paper_realized : s.realized
  const net = paper ? (s.paper_realized + s.paper_upnl) : s.net
  const modeBadge = s.mode === 'mixed'
    ? <Badge size="xs" color="grape">LIVE+DRY</Badge>
    : paper ? <Badge size="xs" color="yellow" variant="light">📄 Тест (бумага)</Badge>
      : <Badge size="xs" color="teal">LIVE</Badge>
  return (
    <Card withBorder p="sm" radius="md">
      <Group justify="space-between" align="flex-start" wrap="nowrap">
        <div>
          <Group gap={8}>
            <Text fw={700}>{s.name}</Text>
            {modeBadge}
            <Badge size="xs" variant="outline" color="gray">{s.data_mode}</Badge>
            {s.reconstructed && <Badge size="xs" variant="dot" color="gray">из логов</Badge>}
          </Group>
          <Text size="xs" c="dimmed" mt={2}>
            {dt(s.started)} {s.ended ? `→ ${dt(s.ended)}` : '· идёт'}
            {s.target && <> · <Anchor size="xs" href={`https://app.hyperliquid.xyz/explorer/address/${s.target}`} target="_blank">{s.target.slice(0, 10)}…↗</Anchor></>}
          </Text>
        </div>
        <Stack gap={0} align="flex-end">
          <Text size="xs" c="dimmed">{paper ? 'ROI (бумага)' : 'Реализованный PnL'}</Text>
          {paper
            ? <Text fw={700} c={s.paper_roi >= 0 ? 'teal' : 'red'}>{s.paper_roi >= 0 ? '+' : ''}{num(s.paper_roi)}%</Text>
            : <Text fw={700}><Pnl v={realized} /></Text>}
        </Stack>
      </Group>

      <SimpleGrid cols={4} mt="sm" spacing="xs">
        <Metric label={paper ? 'Бумажный депозит' : 'Старт. эквити'}>${num(s.start_equity, 0)}</Metric>
        <Metric label={paper ? 'Реализованный PnL' : 'Реализ. PnL (копир)'}><Pnl v={realized} /></Metric>
        {paper
          ? <Metric label="Нереализ. (бумага)"><Pnl v={s.paper_upnl} /></Metric>
          : <Metric label="Фандинг + комса"><Pnl v={(s.funding || 0) + (s.commission || 0)} /></Metric>}
        <Metric label="Итого / нетто"><Pnl v={net} /></Metric>
      </SimpleGrid>
      {!paper && !!s.realized_manual && (
        <Text size="xs" c="dimmed" mt={4}>✋ ручной оверлей: <Pnl v={s.realized_manual} /> ({s.trades_manual || 0} сделок) — не входит в PnL копира</Text>
      )}

      <Group justify="space-between" mt="xs">
        <Text size="xs" c="dimmed">
          {(s.coins?.length || 0) > 0 && <>Монеты: {s.coins.join(', ')} · </>}
          {live && s.trades != null && <>сделок: {s.trades}</>}
        </Text>
        {s.ended
          ? <Badge size="xs" variant="light" color="gray">⊘ {REASON[s.end_reason] || s.end_reason}</Badge>
          : <Badge size="xs" variant="light" color="green">● активна</Badge>}
      </Group>

      {(s.positions?.length > 0) && (
        <>
          <Anchor size="xs" mt={6} onClick={() => setOpen(o => !o)}>{open ? 'Свернуть ▲' : `Позиции (${s.positions.length}) ▾`}</Anchor>
          <Collapse in={open}><Positions rows={s.positions} /></Collapse>
        </>
      )}
    </Card>
  )
}

export default function Journal() {
  const [d, setD] = useState(null)
  const [tab, setTab] = useState('active')
  useEffect(() => {
    let alive = true
    const f = async () => { try { const r = await getCopySessions(); if (alive) setD(r) } catch (e) {} }
    f(); const id = setInterval(f, 15000); return () => { alive = false; clearInterval(id) }
  }, [])

  const t = d?.totals || {}
  const active = d?.active || [], paper = d?.paper || [], closed = d?.closed || []
  const Empty = ({ msg }) => <Text c="dimmed" size="sm" ta="center" py="lg">{msg}</Text>

  return (
    <Stack gap="sm">
      <Card withBorder p="sm" radius="md">
        <SimpleGrid cols={4} spacing="xs">
          <Metric label="Активных сейчас">{t.active ?? '—'}</Metric>
          <Metric label="На бумаге сейчас">{t.paper ?? '—'}</Metric>
          <Metric label="Реализ. PnL (LIVE, закрытые)"><Pnl v={t.live_realized} /></Metric>
          <Metric label="Реализ. PnL (бумага, закрытые)"><Pnl v={t.paper_realized} /></Metric>
        </SimpleGrid>
      </Card>

      <Tabs value={tab} onChange={setTab}>
        <Tabs.List mb="sm">
          <Tabs.Tab value="active">Активный ({active.length})</Tabs.Tab>
          <Tabs.Tab value="paper">Тестовый ({paper.length})</Tabs.Tab>
          <Tabs.Tab value="closed">Закрыто ({closed.length})</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="active">
          {!active.length ? <Empty msg="Нет активных LIVE-сессий копирования" />
            : <Stack gap="sm">{active.map((s) => <SessionCard key={s.id} s={s} />)}</Stack>}
        </Tabs.Panel>
        <Tabs.Panel value="paper">
          {!paper.length ? <Empty msg="Нет бумажных (DRY) сессий. Запусти копир в DRY-режиме — здесь появится симуляция PnL." />
            : <Stack gap="sm">{paper.map((s) => <SessionCard key={s.id} s={s} />)}</Stack>}
        </Tabs.Panel>
        <Tabs.Panel value="closed">
          {!closed.length ? <Empty msg="История сессий пуста" />
            : <Stack gap="sm">{closed.map((s) => <SessionCard key={s.id} s={s} />)}</Stack>}
        </Tabs.Panel>
      </Tabs>
    </Stack>
  )
}
