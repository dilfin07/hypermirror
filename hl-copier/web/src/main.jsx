import React from 'react'
import ReactDOM from 'react-dom/client'
import { MantineProvider } from '@mantine/core'
import { Notifications } from '@mantine/notifications'
import '@mantine/core/styles.css'
import '@mantine/charts/styles.css'
import '@mantine/notifications/styles.css'
import App from './App.jsx'

ReactDOM.createRoot(document.getElementById('root')).render(
  <MantineProvider defaultColorScheme="dark">
    <Notifications position="bottom-right" />
    <App />
  </MantineProvider>
)
