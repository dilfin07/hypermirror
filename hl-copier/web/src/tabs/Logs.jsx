import { useEffect, useState } from 'react'
import { Card, ScrollArea, Text, Badge, Group, SegmentedControl } from '@mantine/core'
import { getLogs } from '../api'

const COLOR = { info: 'gray', trade: 'teal', error: 'red', target: 'cyan', skip: 'yellow', hb: 'dark', monitor: 'violet' }
const FILTERS = [
  { label: 'Всё', value: 'all' },
  { label: 'Монитор', value: 'monitor' },
  { label: 'Активность цели', value: 'target' },
  { label: 'Сделки', value: 'trade' },
  { label: 'Пропуски', value: 'skip' },
  { label: 'Ошибки', value: 'error' },
]

export default function Logs() {
  const [logs, setLogs] = useState([])
  const [filter, setFilter] = useState('all')
  useEffect(() => {
    const f = async () => { try { setLogs((await getLogs()).logs || []) } catch (e) {} }
    f(); const id = setInterval(f, 2500); return () => clearInterval(id)
  }, [])
  const shown = [...logs].reverse().filter((l) => filter === 'all' || l.level === filter)
  return (
    <Card withBorder>
      <SegmentedControl size="xs" mb="xs" value={filter} onChange={setFilter} data={FILTERS} />
      <ScrollArea h={500}>
        {shown.length === 0 && <Text c="dimmed" size="sm">Пусто</Text>}
        {shown.map((l, i) => (
          <Group key={i} gap="xs" wrap="nowrap" mb={2}>
            <Text size="xs" c="dimmed" ff="monospace">{(l.ts || '').slice(11, 19)}</Text>
            <Badge size="xs" color={COLOR[l.level] || 'gray'} w={70} style={{ flexShrink: 0 }}>{l.level}</Badge>
            <Text size="sm">{l.msg}</Text>
          </Group>
        ))}
      </ScrollArea>
    </Card>
  )
}
