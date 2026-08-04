import { createTheme } from '@mantine/core'

// scale — динамический (плотность S/M/L), поэтому фабрика, а не статичный объект
export const makeTheme = (scale) => createTheme({
  primaryColor: 'blue',
  fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
  defaultRadius: 'md',
  scale,
})
