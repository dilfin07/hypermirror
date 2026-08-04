import { useState, useEffect } from 'react'
import { Modal, Stack, Group, Text, Badge, Switch, Button, Alert } from '@mantine/core'
import { Warning, ArrowsLeftRight } from '@phosphor-icons/react'
import { useQueryClient } from '@tanstack/react-query'
import { useJournal, useMeta } from '../api/queries'
import { api } from '../api/client'

const isLong = (p) => p.sideRaw === 'LONG' || p.side === 'ЛОНГ'
const pnlGreen = (s) => typeof s === 'string' && (s.startsWith('+') || (!s.startsWith('-') && !s.startsWith('−')))

// Модалка подтверждения смены активного счёта. Показывает открытые позиции
// текущего счёта; тумблер у позиции = закрыть по рынку перед переключением.
// По умолчанию тумблеры выключены → позиции остаются «дышать» (модель adopt).
export default function SwitchAccountModal({ opened, onClose, target, current }) {
  const { data: journal } = useJournal()
  const { data: meta } = useMeta()
  const qc = useQueryClient()
  const positions = journal?.open || []
  const [closeSet, setCloseSet] = useState(() => new Set())
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => { if (opened) { setCloseSet(new Set()); setErr('') } }, [opened])

  const toggle = (sym) => setCloseSet((s) => {
    const n = new Set(s); n.has(sym) ? n.delete(sym) : n.add(sym); return n
  })

  const confirm = async () => {
    setBusy(true); setErr('')
    try {
      await api.stopBot() // свитч требует остановленного бота; на стопе — no-op
      for (const p of positions) if (closeSet.has(p.sym)) await api.closePosition({ symbol: p.sym, positionSide: p.positionSide })
      await api.setActiveAccount(target.id)
      await qc.invalidateQueries()
      onClose()
    } catch (e) {
      setErr(String(e?.message || e) || 'не удалось переключить')
    } finally { setBusy(false) }
  }

  const nClose = closeSet.size
  return (
    <Modal opened={opened} onClose={busy ? () => {} : onClose} centered radius="md" size="md"
      title={<Group gap={8}><ArrowsLeftRight size={18} weight="bold" /><Text fw={700}>Переключить счёт на «{target?.label}»</Text></Group>}>
      <Stack gap="md">
        <Alert color="yellow" variant="light" icon={<Warning size={16} />} p="sm">
          <Text size="sm">
            Переключение остановит бота на «{current?.label ?? 'текущем'}»{meta?.running ? ' (сейчас торгует)' : ''}.
            По умолчанию открытые позиции <b>остаются</b> — они будут без управления, пока не вернёшься на этот счёт.
            Включи тумблер у позиции, чтобы закрыть её по рынку перед переключением.
          </Text>
        </Alert>

        {positions.length ? (
          <Stack gap={6}>
            <Text size="xs" c="dimmed" tt="uppercase" fw={700}>Открытые позиции на «{current?.label}»</Text>
            {positions.map((p, i) => (
              <Group key={i} justify="space-between" wrap="nowrap" px="sm" py={8}
                style={{ border: '1px solid var(--mantine-color-default-border)', borderRadius: 8 }}>
                <Group gap={8} wrap="nowrap" style={{ minWidth: 0 }}>
                  <Text fw={600} size="sm">{p.sym}</Text>
                  <Badge size="xs" variant="light" color={isLong(p) ? 'teal' : 'red'}>{p.side}</Badge>
                  {p.lev && <Badge size="xs" variant="default">{p.lev}</Badge>}
                  <Text size="xs" c="dimmed" ff="monospace">{p.size} {p.sizeUnit}</Text>
                  <Text size="xs" fw={600} c={pnlGreen(p.pnl) ? 'teal' : 'red'}>{p.pnl} {p.pnlUnit}</Text>
                </Group>
                <Group gap={6} wrap="nowrap">
                  <Text size="xs" fw={600} c={closeSet.has(p.sym) ? 'red' : 'dimmed'}>
                    {closeSet.has(p.sym) ? 'закрыть' : 'оставить'}
                  </Text>
                  <Switch size="sm" color="red" checked={closeSet.has(p.sym)} onChange={() => toggle(p.sym)} />
                </Group>
              </Group>
            ))}
          </Stack>
        ) : (
          <Text size="sm" c="dimmed">Открытых позиций нет — переключение безопасно.</Text>
        )}

        {err && <Text size="xs" c="red">{err}</Text>}

        <Group justify="flex-end" gap="sm">
          <Button variant="default" onClick={onClose} disabled={busy}>Отмена</Button>
          <Button color={nClose ? 'red' : 'blue'} onClick={confirm} loading={busy}>
            {nClose ? `Закрыть ${nClose} и переключить` : 'Переключить'}
          </Button>
        </Group>
      </Stack>
    </Modal>
  )
}
