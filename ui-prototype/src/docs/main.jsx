import React from 'react'
import ReactDOM from 'react-dom/client'
import { MantineProvider, localStorageColorSchemeManager } from '@mantine/core'
import '@mantine/core/styles.css'
import DocsPage from './DocsPage'
import { makeTheme } from '../theme'

// тема (light/dark) общая с приложением — тот же ключ в localStorage
const colorSchemeManager = localStorageColorSchemeManager({ key: 'hlc.color-scheme' })

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <MantineProvider theme={makeTheme(0.9)} defaultColorScheme="light" colorSchemeManager={colorSchemeManager}>
      <DocsPage />
    </MantineProvider>
  </React.StrictMode>,
)
