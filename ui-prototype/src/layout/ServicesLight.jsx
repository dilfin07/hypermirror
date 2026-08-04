import { Popover, Tooltip, UnstyledButton, Group, Box, Text, Stack, Badge } from '@mantine/core'
import { SVC_COLOR, SVC_LABEL } from '../constants'
import { useServices } from '../api/queries'

const Dot = ({ state }) => <Box w={9} h={9} style={{ borderRadius: '50%', background: `var(--mantine-color-${SVC_COLOR[state]}-5)` }} />

// светофор сервисов в шапке: точки + поповер с деталями
export default function ServicesLight() {
  const { data: services = [] } = useServices()
  return (
    <Popover withArrow position="bottom-end" shadow="md" width={240}>
      <Popover.Target>
        <Tooltip label="Состояние сервисов" withArrow>
          <UnstyledButton px={6} py={4} style={{ borderRadius: 8 }}>
            <Group gap={5} wrap="nowrap">{services.map((s) => <Dot key={s.key} state={s.state} />)}</Group>
          </UnstyledButton>
        </Tooltip>
      </Popover.Target>
      <Popover.Dropdown>
        <Text fz={11} fw={700} c="dimmed" tt="uppercase" mb="xs" style={{ letterSpacing: 0.4 }}>Сервисы</Text>
        <Stack gap={8}>
          {services.map((s) => (
            <Group key={s.key} justify="space-between" wrap="nowrap">
              <Group gap={8} wrap="nowrap"><Dot state={s.state} /><Text size="sm">{s.label}</Text></Group>
              <Group gap={6} wrap="nowrap">
                <Text fz={10} c="dimmed">{s.note}</Text>
                <Badge size="xs" color={SVC_COLOR[s.state]} variant="light">{SVC_LABEL[s.state]}</Badge>
              </Group>
            </Group>
          ))}
        </Stack>
      </Popover.Dropdown>
    </Popover>
  )
}
