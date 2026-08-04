import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Прототип UI — отдельный от hl-copier/web (дев) и от прода. Порт 5174 (5173 занят основным фронтом).
// Две страницы: основное приложение (index.html) и документация (docs.html, открывается в соседнем табе).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    host: '127.0.0.1',
    // переезд: API проксируем на дев/боевой бэкенд (читаем живые данные с Pi)
    proxy: { '/api': { target: 'http://localhost:8787', changeOrigin: true } },
  },
  build: {
    rollupOptions: {
      input: { main: 'index.html', docs: 'docs.html' },
    },
  },
})
