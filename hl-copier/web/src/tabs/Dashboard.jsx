import { useEffect, useState } from 'react'
import { Card, Table, Button, Badge, Group, Title, Text, Stack, SimpleGrid, Grid, SegmentedControl, Loader } from '@mantine/core'
import { Sparkline } from '@mantine/charts'
import CalendarHeatmap from '../CalendarHeatmap'
import { getAccountStats } from '../api'

const fmtPx = (x) => (x ? x.toLocaleString('en-US', { maximumFractionDigits: x < 10 ? 5 : 2 }) : '—')

const Loading = ({ label = 'Загрузка…', h = 60 }) => (
  <Group justify="center" align="center" gap="xs" style={{ height: h }}>
    <Loader size="sm" /><Text size="xs" c="dimmed">{label}</Text>
  </Group>
)

function Row({ label, value, color }) {
  return (
    <Group justify="space-between" gap="xs" wrap="nowrap">
      <Text size="xs" c="dimmed" tt="uppercase">{label}</Text>
      <Text fw={700} c={color} ff="monospace">{value}</Text>
    </Group>
  )
}

export default function Dashboard({ s, act }) {
  const pos = s.positions || []
  const desired = s.desired || []
  const targets = s.targets || []

  const [acct, setAcct] = useState({})
  const [acctLoaded, setAcctLoaded] = useState(false)
  const [calView, setCalView] = useState('map')
  useEffect(() => {
    const f = async () => { try { setAcct(await getAccountStats()) } catch (e) {} finally { setAcctLoaded(true) } }
    f(); const id = setInterval(f, 10000); return () => clearInterval(id)
  }, [])
  const ready = s.ready   // статус подтянулся с сервера

  // кумулятивный PnL для кривой
  const cum = (() => {
    const d = acct.daily || {}
    let s = 0
    return Object.keys(d).sort().map((k) => Math.round((s += d[k])))
  })()

  const money = (v) => (v == null ? '—' : `${v >= 0 ? '+' : '-'}$${Math.abs(v).toLocaleString('en-US', { maximumFractionDigits: 2 })}`)

  return (
    <Stack gap="sm">
      {!acctLoaded ? (
        <Card withBorder p="md"><Loading label="Загружаю статистику аккаунта…" h={90} /></Card>
      ) : acct.have_keys && (
        <Grid gutter="sm" align="stretch">
          <Grid.Col span={{ base: 12, sm: 4, md: 3 }}>
            <Card withBorder p="md" h="100%">
              <Text fw={700} size="xs" mb="sm" tt="uppercase" c="dimmed">Обзор перпетуалов</Text>
              <Stack gap="sm">
                <Row label="Нереализованный PnL" value={money(acct.uPnl)} color={acct.uPnl >= 0 ? 'teal' : 'red'} />
                <Row label="Плечо аккаунта" value={`${acct.leverage ?? 0}×`} />
                <Row label="Использование маржи" value={`${acct.margin_usage ?? 0}%`} color="teal" />
                <Row label="PnL за год" value={money(acct.realized_total)} color={(acct.realized_total || 0) >= 0 ? 'teal' : 'red'} />
              </Stack>
            </Card>
          </Grid.Col>
          <Grid.Col span={{ base: 12, sm: 8, md: 9 }}>
            <Card withBorder p="xs" h="100%">
              <Group justify="space-between" mb={6}>
                <Title order={6}>{calView === 'map' ? 'Календарь PnL (Binance, год)' : 'Кривая PnL (накопительно, год)'}</Title>
                <SegmentedControl size="xs" value={calView} onChange={setCalView}
                  data={[{ label: 'Карта', value: 'map' }, { label: 'Кривая', value: 'curve' }]} />
              </Group>
              {calView === 'map' ? (
                <CalendarHeatmap data={acct.daily || {}} />
              ) : cum.length === 0 ? (
                <Text c="dimmed" size="sm">Нет данных</Text>
              ) : (
                <Sparkline h={120} data={cum} curveType="linear" fillOpacity={0.2} strokeWidth={1.5}
                  trendColors={{ positive: 'teal.6', negative: 'red.6', neutral: 'gray.5' }} />
              )}
            </Card>
          </Grid.Col>
        </Grid>
      )}

      <Card withBorder p="xs">
        <Group justify="space-between" mb={6}>
          <Title order={6}>Открытые копии ({pos.length})</Title>
          {pos.length > 0 && (
            <Button size="compact-xs" color="red" variant="light"
              onClick={() => { if (window.confirm('Закрыть все позиции?')) act('/panic') }}>
              Закрыть все
            </Button>
          )}
        </Group>
        {!ready ? (
          <Loading label="Загружаю позиции…" />
        ) : pos.length === 0 ? (
          <Text c="dimmed" size="sm">Нет открытых позиций</Text>
        ) : (
          <Table fz="xs" verticalSpacing={4} horizontalSpacing="sm" highlightOnHover withRowBorders={false}>
            <Table.Thead>
              <Table.Tr style={{ color: 'var(--mantine-color-dimmed)' }}>
                <Table.Th>Символ</Table.Th>
                <Table.Th ta="right">Размер</Table.Th>
                <Table.Th ta="right">Вход</Table.Th>
                <Table.Th ta="right">Марк</Table.Th>
                <Table.Th ta="right">Ликвидация</Table.Th>
                <Table.Th ta="right">Маржа</Table.Th>
                <Table.Th ta="right">PnL (ROI%)</Table.Th>
                <Table.Th ta="right"></Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {pos.map((p, i) => {
                const neg = p.side === 'SHORT'
                return (
                  <Table.Tr key={i}>
                    <Table.Td>
                      <Group gap={6} wrap="nowrap">
                        <Text fw={600} size="xs">{p.symbol}</Text>
                        <Badge size="xs" color={neg ? 'red' : 'teal'} variant="light">{neg ? 'S' : 'L'}</Badge>
                        <Text size="10px" c="dimmed">{p.leverage}x</Text>
                      </Group>
                    </Table.Td>
                    <Table.Td ta="right" c={neg ? 'red' : 'teal'} ff="monospace">
                      {neg ? '-' : '+'}{p.notional} <Text span c="dimmed" size="10px">USDT</Text>
                    </Table.Td>
                    <Table.Td ta="right" ff="monospace">{fmtPx(p.entry)}</Table.Td>
                    <Table.Td ta="right" ff="monospace">{fmtPx(p.mark)}</Table.Td>
                    <Table.Td ta="right" ff="monospace" c="orange">{fmtPx(p.liq)}</Table.Td>
                    <Table.Td ta="right" ff="monospace">{p.margin} <Text span c="dimmed" size="10px">USDT</Text></Table.Td>
                    <Table.Td ta="right" ff="monospace" c={p.uPnl >= 0 ? 'teal' : 'red'}>
                      {p.uPnl >= 0 ? '+' : ''}{p.uPnl}
                      <Text span size="10px"> ({p.roi >= 0 ? '+' : ''}{p.roi}%)</Text>
                    </Table.Td>
                    <Table.Td ta="right">
                      <Button size="compact-xs" color="gray" variant="default"
                        onClick={() => act('/close', { symbol: p.symbol, position_side: p.positionSide })}>
                        Закрыть
                      </Button>
                    </Table.Td>
                  </Table.Tr>
                )
              })}
            </Table.Tbody>
          </Table>
        )}
      </Card>

      <SimpleGrid cols={{ base: 1, md: 2 }} spacing="sm">
        <Card withBorder p="xs">
          <Title order={6} mb={6}>Желаемые (план)</Title>
          {!ready && <Loading label="Загрузка…" h={40} />}
          {ready && desired.length === 0 && <Text c="dimmed" size="sm">—</Text>}
          {ready && desired.map((d, i) => (
            <Group key={i} justify="space-between" gap={6}>
              <Group gap={6}><Badge size="xs" color={d.side === 'SHORT' ? 'red' : 'teal'} variant="light">{d.side === 'SHORT' ? 'S' : 'L'}</Badge><Text size="xs">{d.coin}</Text></Group>
              <Text size="xs" ff="monospace">${Math.round(Math.abs(d.notional))} · {d.leverage}x</Text>
            </Group>
          ))}
          {s.frozen?.length > 0 && <Text size="11px" c="dimmed" mt={6}>❄️ заморожено: {s.frozen.map((f) => f.coin).join(', ')}</Text>}
          {s.disabled?.length > 0 && <Text size="11px" c="orange" mt={2}>⏸ отключено: {s.disabled.join(', ')}</Text>}
        </Card>

        <Card withBorder p="xs">
          <Title order={6} mb={6}>Цели</Title>
          {!ready && <Loading label="Загрузка…" h={40} />}
          {ready && targets.length === 0 && <Text c="dimmed" size="sm">—</Text>}
          {ready && targets.map((t, i) => (
            <div key={i} style={{ marginBottom: 6 }}>
              <Text fw={600} size="xs">{t.label} <Text span c="dimmed">(${(t.equity || 0).toLocaleString()})</Text></Text>
              <Group gap={4} mt={2}>
                {t.positions.map((p, j) => (
                  <Badge key={j} size="xs" variant="light" color={p.side === 'SHORT' ? 'red' : 'teal'}>
                    {p.coin} {p.exposure_pct}%
                  </Badge>
                ))}
              </Group>
            </div>
          ))}
        </Card>
      </SimpleGrid>
    </Stack>
  )
}
