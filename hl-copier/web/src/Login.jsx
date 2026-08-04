import { useState } from 'react'
import { Center, Card, Title, PasswordInput, Button, Text, Stack } from '@mantine/core'
import { login, setToken } from './api'

export default function Login({ onOk }) {
  const [pw, setPw] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    setBusy(true); setErr('')
    const r = await login(pw)
    setBusy(false)
    if (r.token) { setToken(r.token); onOk() }
    else setErr(r.error || 'не удалось войти')
  }

  return (
    <Center h="100vh">
      <Card withBorder p="xl" w={360}>
        <Title order={4} mb="md">HL → Binance Copier</Title>
        <Stack gap="sm">
          <PasswordInput label="Пароль" value={pw} autoFocus
            onChange={(e) => setPw(e.currentTarget.value)}
            onKeyDown={(e) => e.key === 'Enter' && submit()} />
          {err && <Text c="red" size="sm">{err}</Text>}
          <Button onClick={submit} loading={busy} disabled={!pw}>Войти</Button>
        </Stack>
      </Card>
    </Center>
  )
}
