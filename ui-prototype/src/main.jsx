import React from 'react'
import ReactDOM from 'react-dom/client'
import { MantineProvider, localStorageColorSchemeManager } from '@mantine/core'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@mantine/core/styles.css'
import '@mantine/charts/styles.css'
import App from './App'
import { makeTheme } from './theme'
import { PrefsProvider, usePrefs } from './settings/prefs'
import LiveGate from './auth/LiveGate'

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, staleTime: 2000, retry: 1 } },
})

// тема (light/dark) сохраняется Mantine-ом отдельно от наших prefs
const colorSchemeManager = localStorageColorSchemeManager({ key: 'hlc.color-scheme' })

// тема пересобирается при смене масштаба (scale жмёт всю плотность)
function Themed() {
  const { scale } = usePrefs()
  return (
    <MantineProvider theme={makeTheme(scale)} defaultColorScheme="light" colorSchemeManager={colorSchemeManager}>
      <QueryClientProvider client={queryClient}>
        <LiveGate><App /></LiveGate>
      </QueryClientProvider>
    </MantineProvider>
  )
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <PrefsProvider>
      <Themed />
    </PrefsProvider>
  </React.StrictMode>,
)
