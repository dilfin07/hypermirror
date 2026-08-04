import { useEffect, useState } from 'react'
import {
  Card, Group, Title, Text, TextInput, Button, Badge, Stack, ActionIcon, Tooltip,
  Progress, SimpleGrid,
} from '@mantine/core'
import { getMonitors, post } from '../api'

const usd = (v) => (v == null ? '—' : `$${Math.round(v).toLocaleString('en-US')}`)
const signed = (v) => (v == null ? '—' : `${v >= 0 ? '+' : '-'}$${Math.abs(v).toLocaleString('en-US', { maximumFractionDigits: 2 })}`)
const px = (x) => (x ? x.toLocaleString('en-US', { maximumFractionDigits: x < 10 ? 5 : 2 }) : '—')

function Metric({ label, value, color, w = 108 }) {
  return (
    <div style={{ width: w, flexShrink: 0 }}>
      <Text size="10px" c="dimmed">{label}</Text>
      <Text size="sm" fw={600} c={color}>{value}</Text>
    </div>
  )
}

export default function Monitor() {
  const [mons, setMons] = useState([])
  const [addr, setAddr] = useState('')
  const [name, setName] = useState('')
  const [msg, setMsg] = useState('')
  const [open, setOpen] = useState({})

  const load = async () => { try { setMons((await getMonitors()).monitors || []) } catch (e) {} }
  useEffect(() => { load(); const id = setInterval(load, 8000); return () => clearInterval(id) }, [])

  // живое обновление раскрытых строк: свежий запрос к бирже каждые 4с
  useEffect(() => {
    const openAddrs = Object.keys(open).filter((a) => open[a])
    if (!openAddrs.length) return
    const tick = async () => {
      for (const a of openAddrs) {
        const r = await post('/monitor_refresh', { address: a })
        if (r && r.monitor) setMons((prev) => prev.map((m) => (m.address === a ? r.monitor : m)))
      }
    }
    tick()
    const id = setInterval(tick, 4000)
    return () => clearInterval(id)
  }, [open])

  const add = async () => {
    const r = await post('/monitor_add', { address: addr, name })
    setMsg(r.error || 'Добавлено — алерты пойдут в Telegram')
    if (!r.error) { setAddr(''); setName('') }
    load()
  }
  const remove = async (a) => { await post('/monitor_remove', { address: a }); load() }
  const toggle = async (a) => { await post('/monitor_toggle', { address: a }); load() }
  const copySet = async (a) => { await post('/copy_set', { address: a }); load() }
  const copyClear = async () => { await post('/copy_clear', {}); load() }

  return (
    <Stack>
      <Card withBorder p="md">
        <Title order={6} mb="xs">Добавить адрес в монитор</Title>
        <Group align="end">
          <TextInput style={{ flex: 1 }} label="Адрес кошелька" placeholder="0x…" value={addr} onChange={(e) => setAddr(e.currentTarget.value)} />
          <TextInput w={220} label="Своё имя (метка)" placeholder="напр. свинг-наблюдаю" value={name} onChange={(e) => setName(e.currentTarget.value)} />
          <Button onClick={add} disabled={!addr}>Добавить</Button>
        </Group>
        {msg && <Text size="sm" c="dimmed" mt={6}>{msg}</Text>}
        <Text size="xs" c="dimmed" mt={6}>
          Бот следит за позициями и шлёт в Telegram действия (открыл/долил/сократил/закрыл).
          Имя из сети — с Hyperdash. Колокол 🔔 — вкл/выкл алертов по адресу.
        </Text>
      </Card>

      <Stack gap={8}>
        {mons.length === 0 && <Text c="dimmed" size="sm">Пусто — добавь адрес сверху</Text>}
        {mons.map((m) => {
          const exp = !!open[m.address]
          const positions = m.positions || []
          return (
            <Card key={m.address} withBorder p="xs">
              <Group wrap="wrap" gap="sm" align="center">
                <div style={{ width: 180, flexShrink: 0 }}>
                  <Group gap={6} wrap="nowrap">
                    <Text fw={700} size="sm">{m.name || m.address.slice(0, 8)}</Text>
                    {m.copying && <Badge size="xs" variant="filled" color="orange">📋 копир</Badge>}
                  </Group>
                  <Text size="11px" c="dimmed" ff="monospace">{m.address.slice(0, 10)}…</Text>
                </div>
                <Metric label="Perp Total Value" value={usd(m.equity)} />
                <Metric label="Спот (кэш)" value={usd(m.spot_usd)} />
                <Metric label="Капитал (база)" value={usd(m.basis)} color="blue" />
                <Metric label="uPnL" value={signed(m.uPnl)} color={(m.uPnl || 0) >= 0 ? 'teal' : 'red'} />
                <Metric label="Free margin" value={usd(m.free_margin)} />
                <div style={{ width: 132, flexShrink: 0 }}>
                  <Text size="10px" c="dimmed">Margin Used Ratio</Text>
                  <Group gap={6} wrap="nowrap">
                    <Progress value={Math.min(100, m.margin_ratio || 0)} w={56} size="sm"
                      color={(m.margin_ratio || 0) > 80 ? 'red' : (m.margin_ratio || 0) > 50 ? 'yellow' : 'teal'} />
                    <Text size="sm" fw={600}>{m.margin_ratio ?? 0}%</Text>
                  </Group>
                </div>
                <Metric label="Positions" value={positions.length} w={70} />
                <Group gap={4} wrap="nowrap" ml="auto" style={{ flexShrink: 0 }}>
                  {m.copying
                    ? <Button size="compact-xs" color="orange" variant="light" onClick={copyClear}>Убрать из копира</Button>
                    : <Button size="compact-xs" variant="default" onClick={() => copySet(m.address)}>→ В копир</Button>}
                  <Tooltip label={m.alerts ? 'Алерты вкл' : 'Алерты выкл'} withArrow>
                    <ActionIcon variant={m.alerts ? 'filled' : 'light'} color={m.alerts ? 'teal' : 'gray'} onClick={() => toggle(m.address)}>🔔</ActionIcon>
                  </Tooltip>
                  <Tooltip label="Hyperdash" withArrow>
                    <ActionIcon variant="light" color="blue" component="a" href={`https://hyperdash.com/address/${m.address}`} target="_blank">↗</ActionIcon>
                  </Tooltip>
                  <ActionIcon variant="light" color="red" onClick={() => remove(m.address)}>✕</ActionIcon>
                  <ActionIcon variant="subtle" onClick={() => setOpen({ ...open, [m.address]: !exp })}>{exp ? '▲' : '▼'}</ActionIcon>
                </Group>
              </Group>

              {exp && positions.length > 0 && (
                <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} mt="sm" spacing="xs">
                  {positions.map((p, i) => (
                    <Card key={i} withBorder p="xs" radius="sm" bg="var(--mantine-color-dark-8)">
                      <Group gap={6} wrap="nowrap">
                        <Text fw={700} size="sm">{p.coin}</Text>
                        <Text size="xs" c="dimmed">${px(p.entry)}</Text>
                        <Badge size="xs" color={p.side === 'SHORT' ? 'red' : 'teal'}>{p.side === 'SHORT' ? 'Short' : 'Long'}</Badge>
                        <Text size="xs" c="dimmed">{p.lev_type === 'isolated' ? 'Изолир' : 'Cross'} {p.lev}x</Text>
                      </Group>
                      <SimpleGrid cols={3} mt={6} spacing={4}>
                        <div><Text size="10px" c="dimmed">Объём</Text><Text size="xs" ff="monospace">{usd(p.position_value)}</Text></div>
                        <div><Text size="10px" c="dimmed">uPnL</Text><Text size="xs" ff="monospace" c={p.uPnl >= 0 ? 'teal' : 'red'}>{signed(p.uPnl)}<br />{p.roe >= 0 ? '+' : ''}{p.roe}%</Text></div>
                        <div><Text size="10px" c="dimmed">Маржа</Text><Text size="xs" ff="monospace">{usd(p.margin)}</Text></div>
                      </SimpleGrid>
                    </Card>
                  ))}
                </SimpleGrid>
              )}
            </Card>
          )
        })}
      </Stack>
    </Stack>
  )
}
