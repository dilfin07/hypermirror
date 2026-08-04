import { Group, UnstyledButton } from '@mantine/core'
import { TABS, NAV_INACTIVE } from '../constants'
import { useT } from '../settings/i18n'

// тонкий верхний таб-бар: активный = синий текст + короткое подчёркивание
export default function TopNav({ value, onChange }) {
  const t = useT()
  return (
    <Group gap={2} wrap="nowrap">
      {TABS.map((tab) => {
        const act = tab.value === value
        return (
          <UnstyledButton key={tab.value} onClick={() => onChange(tab.value)}
            style={{
              padding: '6px 14px 5px', fontSize: 14, fontWeight: 500, lineHeight: 1.3,
              color: act ? 'var(--mantine-color-blue-6)' : NAV_INACTIVE,
              borderBottom: `2px solid ${act ? 'var(--mantine-color-blue-6)' : 'transparent'}`,
            }}>
            {t(`nav.${tab.value}`)}
          </UnstyledButton>
        )
      })}
    </Group>
  )
}
