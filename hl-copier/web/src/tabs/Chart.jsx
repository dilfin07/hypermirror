import { useEffect, useRef, useState } from 'react'
import { createChart, ColorType } from 'lightweight-charts'
import { Card, Group, Select, Title, Text, Table, Badge, Button } from '@mantine/core'
import { getKlines, getTrades } from '../api'

const SYMS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'HYPEUSDT', 'XRPUSDT', 'SUIUSDT']
const INTERVALS = ['5m', '15m', '1h', '4h', '1d']
const fmtPx = (x) => (x ? x.toLocaleString('en-US', { maximumFractionDigits: x < 10 ? 5 : 2 }) : '—')

export default function Chart({ s, act }) {
  const pos = s?.positions || []
  const openSyms = pos.map((p) => p.symbol)
  const [symbol, setSymbol] = useState(openSyms[0] || 'BTCUSDT')
  const [interval, setIntervalV] = useState('15m')
  const elRef = useRef(null)
  const chartRef = useRef(null)
  const seriesRef = useRef(null)

  // создаём график один раз + ResizeObserver (фикс нулевой ширины в табе)
  useEffect(() => {
    const chart = createChart(elRef.current, {
      width: elRef.current.clientWidth || 600,
      height: 460,
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#909296' },
      grid: { vertLines: { color: '#25262b' }, horzLines: { color: '#25262b' } },
      timeScale: { timeVisible: true, borderColor: '#373a40' },
      rightPriceScale: { borderColor: '#373a40' },
    })
    const series = chart.addCandlestickSeries({
      upColor: '#2f9e44', downColor: '#e03131', borderVisible: false,
      wickUpColor: '#2f9e44', wickDownColor: '#e03131',
    })
    chartRef.current = chart
    seriesRef.current = series
    const ro = new ResizeObserver((entries) => {
      const w = Math.floor(entries[0].contentRect.width)
      if (w > 0) chart.applyOptions({ width: w })
    })
    ro.observe(elRef.current)
    return () => { ro.disconnect(); chart.remove() }
  }, [])

  // данные при смене символа/таймфрейма + автообновление
  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const kl = await getKlines(symbol, interval)
        if (!alive || !Array.isArray(kl) || !seriesRef.current) return
        seriesRef.current.setData(kl.map((k) => ({
          time: Math.floor(k[0] / 1000), open: +k[1], high: +k[2], low: +k[3], close: +k[4],
        })))
        const tr = await getTrades(symbol)
        if (alive && Array.isArray(tr)) {
          const seen = new Set()
          const markers = tr.map((t) => {
            const isBuy = t.side ? t.side === 'BUY' : t.buyer
            return {
              time: Math.floor(t.time / 1000),
              position: isBuy ? 'belowBar' : 'aboveBar',
              color: isBuy ? '#2f9e44' : '#e03131',
              shape: isBuy ? 'arrowUp' : 'arrowDown',
              text: `${isBuy ? 'BUY' : 'SELL'} ${(+t.qty).toFixed(3)}`,
            }
          }).sort((a, b) => a.time - b.time).filter((m) => {
            const k = m.time + m.shape
            if (seen.has(k)) return false
            seen.add(k); return true
          })
          seriesRef.current.setMarkers(markers)
        }
      } catch (e) {}
    }
    load()
    const id = setInterval(load, 15000)
    return () => { alive = false; clearInterval(id) }
  }, [symbol, interval])

  const symData = [...new Set([...openSyms, ...SYMS])]

  return (
    <>
      <Card withBorder p="xs" mb="sm">
        <Group justify="space-between" mb="xs">
          <Group gap="xs">
            <Title order={6}>{symbol}</Title>
            <Text size="xs" c="dimmed">🟢 BUY снизу · 🔴 SELL сверху — наши сделки</Text>
          </Group>
          <Group gap="xs">
            <Select size="xs" w={130} data={symData} value={symbol} onChange={(v) => v && setSymbol(v)} />
            <Select size="xs" w={90} data={INTERVALS} value={interval} onChange={(v) => v && setIntervalV(v)} />
          </Group>
        </Group>
        <div ref={elRef} style={{ width: '100%', height: 460 }} />
      </Card>

      <Card withBorder p="xs">
        <Title order={6} mb={6}>Открытые копии ({pos.length}) — клик по строке открывает график тикера</Title>
        {pos.length === 0 ? (
          <Text c="dimmed" size="sm">Нет открытых позиций</Text>
        ) : (
          <Table fz="xs" verticalSpacing={8} horizontalSpacing="md" highlightOnHover>
            <Table.Thead>
              <Table.Tr style={{ color: 'var(--mantine-color-dimmed)' }}>
                <Table.Th>Символ</Table.Th>
                <Table.Th ta="right">Размер</Table.Th>
                <Table.Th ta="right">Цена входа</Table.Th>
                <Table.Th ta="right">Безубыток</Table.Th>
                <Table.Th ta="right">Маркировка</Table.Th>
                <Table.Th ta="right">Ликвидация</Table.Th>
                <Table.Th ta="right">Коэфф. маржи</Table.Th>
                <Table.Th ta="right">Маржа</Table.Th>
                <Table.Th ta="right">PnL (ROI, %)</Table.Th>
                <Table.Th ta="right">Финансир.</Table.Th>
                <Table.Th ta="right"></Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {pos.map((p, i) => {
                const neg = p.side === 'SHORT'
                const active = p.symbol === symbol
                const mt = p.margin_type === 'isolated' ? 'Изолир' : 'Кросс'
                return (
                  <Table.Tr key={i} onClick={() => setSymbol(p.symbol)} style={{ cursor: 'pointer' }}
                    bg={active ? 'var(--mantine-color-dark-6)' : undefined}>
                    <Table.Td style={{ borderLeft: `3px solid ${neg ? '#e03131' : '#2f9e44'}` }}>
                      <Text fw={600} size="sm" c={active ? 'blue' : undefined}>{p.symbol}</Text>
                      <Group gap={4} mt={2}>
                        <Badge size="xs" variant="default" color="gray">Бессроч</Badge>
                        <Badge size="xs" variant="default" color="gray">{p.leverage}x</Badge>
                        <Badge size="xs" variant="light" color={neg ? 'red' : 'teal'}>{neg ? 'Шорт' : 'Лонг'}</Badge>
                      </Group>
                    </Table.Td>
                    <Table.Td ta="right" c={neg ? 'red' : 'teal'} ff="monospace">
                      {neg ? '-' : '+'}{p.notional} <Text span c="dimmed" size="10px">USDT</Text>
                    </Table.Td>
                    <Table.Td ta="right" ff="monospace">{fmtPx(p.entry)}</Table.Td>
                    <Table.Td ta="right" ff="monospace" c="dimmed">{fmtPx(p.breakeven)}</Table.Td>
                    <Table.Td ta="right" ff="monospace">{fmtPx(p.mark)}</Table.Td>
                    <Table.Td ta="right" ff="monospace" c="orange">{fmtPx(p.liq)}</Table.Td>
                    <Table.Td ta="right" ff="monospace">{s.margin_ratio ?? 0}%</Table.Td>
                    <Table.Td ta="right" ff="monospace">
                      {p.margin} <Text span c="dimmed" size="10px">USDT ({mt})</Text>
                    </Table.Td>
                    <Table.Td ta="right" ff="monospace" c={p.uPnl >= 0 ? 'teal' : 'red'}>
                      {p.uPnl >= 0 ? '+' : ''}{p.uPnl} USDT<br />
                      <Text span size="10px">{p.roi >= 0 ? '+' : ''}{p.roi}%</Text>
                    </Table.Td>
                    <Table.Td ta="right" ff="monospace" c={p.funding_est >= 0 ? 'teal' : 'red'}>
                      {p.funding_est >= 0 ? '+' : ''}{p.funding_est}<br />
                      <Text span size="10px" c="dimmed">{p.funding_rate}%</Text>
                    </Table.Td>
                    <Table.Td ta="right">
                      <Button size="compact-xs" color="gray" variant="default"
                        onClick={(e) => { e.stopPropagation(); act('/close', { symbol: p.symbol, position_side: p.positionSide }) }}>
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
    </>
  )
}
