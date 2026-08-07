import { useState } from 'react'
import { Group, Box, Text, Select, ActionIcon, Avatar, Tooltip, Divider, Button, Badge } from '@mantine/core'
import { FolderOpen, Gear, Lightning, CaretDown, ListBullets, Play, Stop } from '@phosphor-icons/react'
import TopNav from './TopNav'
import ServicesLight from './ServicesLight'
import SwitchAccountModal from './SwitchAccountModal'
import { useMeta, useAccounts, useCopierControl } from '../api/queries'
import { useT } from '../settings/i18n'

// Управление копиром: Старт (DRY/LIVE) / Стоп. LIVE — с подтверждением (ордера идут на биржу).
function CopierControl() {
  const { data: meta } = useMeta()
  const { start, stop, starting, stopping } = useCopierControl()
  const mode = meta?.mode || 'ws'
  if (meta?.running) {
    return (
      <Group gap={6} wrap="nowrap">
        <Badge size="sm" radius="sm" color={meta.live ? 'red' : 'gray'} variant={meta.live ? 'filled' : 'light'}>
          {meta.live ? '🔴 LIVE' : 'DRY'}
        </Badge>
        <Button size="xs" variant="light" color="red" leftSection={<Stop size={13} weight="fill" />}
          loading={stopping} onClick={() => stop()}>Стоп</Button>
      </Group>
    )
  }
  return (
    <Group gap={5} wrap="nowrap">
      <Button size="xs" variant="default" leftSection={<Play size={12} weight="fill" />}
        loading={starting} onClick={() => start({ live: false, mode })}>DRY</Button>
      <Button size="xs" variant="filled" color="red" leftSection={<Play size={12} weight="fill" />}
        loading={starting}
        onClick={() => { if (window.confirm('Запустить копир в БОЕВОМ режиме (LIVE)? Ордера пойдут на биржу.')) start({ live: true, mode }) }}>
        LIVE
      </Button>
    </Group>
  )
}

function Brand() {
  return (
    <Group gap={8} wrap="nowrap">
      <Box w={28} h={28} style={{ borderRadius: 7, background: 'var(--mantine-color-blue-6)', display: 'grid', placeItems: 'center' }}>
        <Lightning size={17} weight="fill" color="white" />
      </Box>
      <Text fw={700} size="sm">Kielwater</Text>
    </Group>
  )
}

export default function Header({ tab, setTab }) {
  const { data: meta } = useMeta()
  const { data: accounts = [] } = useAccounts()
  const t = useT()
  const [target, setTarget] = useState(null) // счёт, на который запрошено переключение (открывает модалку)
  const activeId = meta?.activeAccount ?? 'main'
  const current = accounts.find((a) => a.id === activeId)
  return (
    <Group h="100%" px="md" justify="space-between" wrap="nowrap" gap="md">
      <Group gap="lg" wrap="nowrap">
        <Brand />
        <Select size="xs" w={185} variant="filled" allowDeselect={false}
          value={activeId} onChange={(v) => { if (v && v !== activeId) setTarget(accounts.find((a) => a.id === v)) }}
          leftSection={<FolderOpen size={15} />} rightSection={<CaretDown size={13} />}
          data={accounts.map((a) => ({ value: a.id, label: a.label }))} />
        <SwitchAccountModal opened={!!target} target={target} current={current} onClose={() => setTarget(null)} />
        <TopNav value={tab} onChange={setTab} />
      </Group>
      <Group gap="sm" wrap="nowrap">
        <CopierControl />
        <Divider orientation="vertical" />
        <ServicesLight />
        <Tooltip label={t('header.logs')} withArrow>
          <ActionIcon variant={tab === 'logs' ? 'light' : 'subtle'} color="gray" size="lg" onClick={() => setTab('logs')}><ListBullets size={19} /></ActionIcon>
        </Tooltip>
        <Divider orientation="vertical" />
        <Text fw={700} size="sm">{meta?.balance ?? '—'}</Text>
        <Tooltip label={t('header.settings')} withArrow>
          <ActionIcon variant={tab === 'settings' ? 'light' : 'subtle'} color="gray" size="lg" onClick={() => setTab('settings')}><Gear size={19} /></ActionIcon>
        </Tooltip>
        <Avatar size="sm" color="blue" radius="xl">D</Avatar>
      </Group>
    </Group>
  )
}
