import { useState } from 'react'
import { Box, Group, Title, Button, Paper, UnstyledButton, ScrollArea, Table, Text, Badge } from '@mantine/core'
import { ArrowsClockwise } from '@phosphor-icons/react'
import { useQueryClient } from '@tanstack/react-query'
import { CARD, LVL, LOG_FILTERS, HAIRLINE, NAV_INACTIVE, ACTIVE_BG, ACTIVE_FG } from '../constants'
import { useLogs } from '../api/queries'
import { useT } from '../settings/i18n'

export default function LogsView() {
  const [f, setF] = useState('all')
  const { data: logs = [] } = useLogs()
  const t = useT()
  const qc = useQueryClient()
  const rows = logs.filter((l) => f === 'all' || l.level === f)
  return (
    <Box p="lg" maw={1500} mx="auto">
      <Group justify="space-between" mb="md">
        <Title order={4}>{t('view.logs.title')}</Title>
        <Button size="compact-xs" variant="default" leftSection={<ArrowsClockwise size={13} />} onClick={() => qc.invalidateQueries({ queryKey: ['logs'] })}>{t('view.logs.refresh')}</Button>
      </Group>
      <Paper withBorder radius="md" style={CARD}>
        <Group gap={2} p={6} style={{ borderBottom: `1px solid ${HAIRLINE}`, overflowX: 'auto' }} wrap="nowrap">
          {LOG_FILTERS.map((ft) => {
            const act = f === ft.value
            return (
              <UnstyledButton key={ft.value} onClick={() => setF(ft.value)}
                style={{ padding: '5px 12px', borderRadius: 7, fontSize: 13, fontWeight: act ? 600 : 500, whiteSpace: 'nowrap',
                  color: act ? ACTIVE_FG : NAV_INACTIVE, background: act ? ACTIVE_BG : 'transparent' }}>
                {t(`log.filter.${ft.value}`)}
              </UnstyledButton>
            )
          })}
        </Group>
        <ScrollArea.Autosize mah="calc(100vh - 260px)">
          <Table verticalSpacing={6} horizontalSpacing="md" highlightOnHover>
            <Table.Tbody>
              {rows.map((l, i) => (
                <Table.Tr key={i}>
                  <Table.Td style={{ width: 1, whiteSpace: 'nowrap' }}><Text fz={12} c="dimmed" ff="monospace">{l.ts}</Text></Table.Td>
                  <Table.Td style={{ width: 1, whiteSpace: 'nowrap' }}><Badge size="xs" color={LVL[l.level]?.color} variant="light" styles={{ label: { overflow: 'visible' } }}>{LVL[l.level]?.tag}</Badge></Table.Td>
                  <Table.Td><Text fz={13}>{l.msg}</Text></Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </ScrollArea.Autosize>
      </Paper>
    </Box>
  )
}
