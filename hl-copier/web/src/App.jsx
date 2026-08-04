import { useEffect, useRef, useState } from 'react'
import { Container, Group, Title, Badge, Button, Tabs, Text, SegmentedControl, Tooltip } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { getStatus, getLogs, authStatus, post } from './api'
import Login from './Login'
import Dashboard from './tabs/Dashboard'
import Chart from './tabs/Chart'
import Monitor from './tabs/Monitor'
import Journal from './tabs/Journal'
import Logs from './tabs/Logs'
import Settings from './tabs/Settings'
import StatusBar from './StatusBar'

const TOAST_LEVELS = { trade: 'teal', error: 'red' }

export default function App() {
  const [status, setStatus] = useState({})
  const [mode, setMode] = useState('poll')
  const [online, setOnline] = useState(false)
  const [auth, setAuth] = useState('checking')

  useEffect(() => {
    const check = async () => {
      try {
        const s = await authStatus()
        setAuth(!s.auth_enabled || localStorage.getItem('hlc_token') ? 'ok' : 'need')
      } catch (e) { setAuth('need') }
    }
    check()
    const onUnauth = () => setAuth('need')
    window.addEventListener('hlc-unauth', onUnauth)
    return () => window.removeEventListener('hlc-unauth', onUnauth)
  }, [])
  const refresh = async () => {
    try { setStatus(await getStatus()); setOnline(true) } catch (e) { setOnline(false) }
  }
  useEffect(() => { refresh(); const id = setInterval(refresh, 3000); return () => clearInterval(id) }, [])
  useEffect(() => { if (status.data_mode && !status.running) setMode(status.data_mode) }, [status.data_mode, status.running])

  // всплывашки на новые сделки/ошибки
  const lastTs = useRef(null)
  useEffect(() => {
    const poll = async () => {
      try {
        const { logs } = await getLogs()
        if (!logs?.length) return
        if (lastTs.current === null) { lastTs.current = logs[logs.length - 1].ts; return }
        logs.filter((l) => l.ts > lastTs.current && TOAST_LEVELS[l.level]).forEach((l) =>
          notifications.show({ message: l.msg, color: TOAST_LEVELS[l.level], autoClose: 6000 }))
        lastTs.current = logs[logs.length - 1].ts
      } catch (e) {}
    }
    poll(); const id = setInterval(poll, 2500); return () => clearInterval(id)
  }, [])

  if (auth === 'need') return <Login onOk={() => setAuth('ok')} />

  const s = status || {}
  const act = async (p, b) => { await post(p, b); refresh() }
  const panic = async () => {
    if (window.confirm('Закрыть ВСЕ позиции и остановить бота?')) { await post('/panic'); refresh() }
  }

  return (
    <>
    <Container size="xl" py="md" pb={56}>
      <Group justify="space-between" mb="md" wrap="wrap">
        <Group>
          <Title order={3}>HL → Binance Copier</Title>
          {(() => {
            const stale = s.tick_age_sec != null && s.tick_age_sec > 20
            const ok = online && !stale
            return (
              <Tooltip label={ok ? `На связи · слушает сеть (${s.tick_age_sec ?? '?'}с назад)` : (online ? 'Задержка данных' : 'Нет связи с ботом')} withArrow>
                <Badge color={ok ? 'teal' : online ? 'yellow' : 'red'} variant="dot">
                  {ok ? 'На связи' : online ? 'Задержка' : 'Нет связи'}
                </Badge>
              </Tooltip>
            )
          })()}
          <Badge color={s.network === 'mainnet' ? 'red' : 'gray'}>{s.network || '—'}</Badge>
          <Badge color={s.live ? 'red' : 'green'}>{s.live ? 'LIVE' : 'DRY-RUN'}</Badge>
          <Badge color={s.running ? 'teal' : 'gray'}>{s.running ? 'RUNNING' : 'STOPPED'}</Badge>
          {s.running && s.data_mode && <Badge color="blue">{s.data_mode === 'ws' ? 'СОКЕТ' : 'ОПРОС'}</Badge>}
          {s.hedge !== undefined && <Badge color="grape">{s.hedge ? 'Hedge' : 'One-way'}</Badge>}
        </Group>
        <Group>
          <Text fw={700}>{s.equity != null ? `$${s.equity}` : '—'}</Text>
          <Tooltip label="Опрос: спрашиваем API раз в N сек. Сокет: мгновенно по сделкам цели (нужен запуск через .venv)." multiline w={260} withArrow>
            <SegmentedControl size="xs" value={mode} onChange={setMode} disabled={s.running}
              data={[{ label: 'Опрос', value: 'poll' }, { label: 'Сокет', value: 'ws' }]} />
          </Tooltip>
          {!s.running ? (
            <>
              <Button size="xs" color="green" onClick={() => act('/start', { live: false, mode })}>Старт (dry)</Button>
              <Button size="xs" color="orange" onClick={() => act('/start', { live: true, mode })}>Старт LIVE</Button>
            </>
          ) : (
            <Button size="xs" variant="default" onClick={() => act('/stop')}>Стоп</Button>
          )}
          <Button size="xs" color="red" onClick={panic}>🚨 PANIC</Button>
        </Group>
      </Group>

      <Tabs defaultValue="dash">
        <Tabs.List>
          <Tabs.Tab value="dash">Дашборд</Tabs.Tab>
          <Tabs.Tab value="chart">График</Tabs.Tab>
          <Tabs.Tab value="monitor">Монитор</Tabs.Tab>
          <Tabs.Tab value="journal">Журнал</Tabs.Tab>
          <Tabs.Tab value="logs">Логи</Tabs.Tab>
          <Tabs.Tab value="settings">Настройки</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="dash" pt="md"><Dashboard s={s} act={act} /></Tabs.Panel>
        <Tabs.Panel value="chart" pt="md"><Chart s={s} act={act} /></Tabs.Panel>
        <Tabs.Panel value="monitor" pt="md"><Monitor /></Tabs.Panel>
        <Tabs.Panel value="journal" pt="md"><Journal /></Tabs.Panel>
        <Tabs.Panel value="logs" pt="md"><Logs /></Tabs.Panel>
        <Tabs.Panel value="settings" pt="md"><Settings /></Tabs.Panel>
      </Tabs>
    </Container>
    <StatusBar s={s} online={online} mode={mode} setMode={setMode} act={act} panic={panic} />
    </>
  )
}
