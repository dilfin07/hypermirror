import { useState } from 'react'
import { AppShell } from '@mantine/core'
import Header from './layout/Header'
import Footer from './layout/Footer'
import JournalView from './views/JournalView'
import MonitorView from './views/MonitorView'
import LogsView from './views/LogsView'
import SettingsView from './views/SettingsView'

// роутинг по табам (settings обрабатывается отдельно — нужны пропсы масштаба)
const VIEWS = {
  journal: JournalView,
  monitor: MonitorView,
  logs: LogsView,
}

export default function App() {
  const [tab, setTab] = useState('journal')
  const View = VIEWS[tab]
  return (
    <AppShell header={{ height: 52 }} footer={{ height: 34 }} padding={0}>
      <AppShell.Header><Header tab={tab} setTab={setTab} /></AppShell.Header>
      <AppShell.Main style={{ height: 'calc(100vh - 52px - 34px)' }}>
        {tab === 'settings' ? <SettingsView /> : View && <View />}
      </AppShell.Main>
      <AppShell.Footer><Footer /></AppShell.Footer>
    </AppShell>
  )
}
