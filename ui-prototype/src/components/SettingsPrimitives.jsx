import { Group, Box, Text, Divider, Badge } from '@mantine/core'
import { CW } from '../constants'
import { useT } from '../settings/i18n'

// бейдж области действия параметра: «на счёт» (оверрайд активного) / «глобально» (общий)
export function ScopeBadge({ scope }) {
  const t = useT()
  const global = scope === 'global'
  return <Badge size="xs" variant="light" color={global ? 'gray' : 'blue'}>{t(global ? 'set.scope.global' : 'set.scope.account')}</Badge>
}

// строка настройки: метка+подсказка слева, контрол справа в колонке фикс. ширины
export function Row({ label, hint, scope, children }) {
  return (
    <Group justify="space-between" wrap="nowrap" align="center" py={10}>
      <Box maw={460}>
        <Group gap={6} wrap="nowrap">
          <Text size="sm" fw={500}>{label}</Text>
          {scope && <ScopeBadge scope={scope} />}
        </Group>
        {hint && <Text size="xs" c="dimmed" mt={2}>{hint}</Text>}
      </Box>
      <Box style={{ flexShrink: 0, width: CW, display: 'flex', justifyContent: 'flex-end' }}>{children}</Box>
    </Group>
  )
}

export function Section({ title, children }) {
  return (
    <Box mb="xl">
      <Text size="xs" tt="uppercase" fw={700} c="dimmed" mb={4} style={{ letterSpacing: 0.4 }}>{title}</Text>
      <Divider mb={14} />
      {children}
    </Box>
  )
}
