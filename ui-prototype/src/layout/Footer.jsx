import { useEffect, useState } from 'react'
import { Group, Text, Anchor } from '@mantine/core'
import { FileText, Clock, Heart } from '@phosphor-icons/react'
import { usePrefs } from '../settings/prefs'
import { useT, TIMEZONES } from '../settings/i18n'
import { REFERRAL_URL } from '../constants'

// живые часы по выбранному поясу — наглядное применение настройки «Часовой пояс»
function TzClock() {
  const { tz } = usePrefs()
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(id)
  }, [])
  const z = TIMEZONES.find((x) => x.value === tz) || TIMEZONES[0]
  const time = new Intl.DateTimeFormat('ru-RU', { timeZone: z.zone, hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(now)
  return (
    <Group gap={5} wrap="nowrap">
      <Clock size={13} />
      <Text size="xs" c="dimmed" ff="monospace">{time} {z.short}</Text>
    </Group>
  )
}

export default function Footer() {
  const t = useT()
  return (
    <Group h="100%" px="md" justify="space-between" wrap="nowrap">
      <Group gap="md" wrap="nowrap">
        <Text size="xs" c="dimmed">{t('footer.copyright')}</Text>
        <TzClock />
        <Anchor size="xs" c="dimmed" underline="never" href={REFERRAL_URL} target="_blank" rel="noopener">
          <Group gap={5} wrap="nowrap"><Heart size={13} weight="fill" color="var(--mantine-color-pink-5)" />{t('footer.support')}</Group>
        </Anchor>
      </Group>
      <Anchor size="xs" c="dimmed" underline="never" href={`${import.meta.env.BASE_URL}docs.html`} target="_blank" rel="noopener">
        <Group gap={5} wrap="nowrap"><FileText size={14} />{t('footer.docs')}</Group>
      </Anchor>
    </Group>
  )
}
