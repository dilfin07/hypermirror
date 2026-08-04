import { useState, useEffect } from 'react'
import { Group, Text, Tooltip, Popover, ActionIcon, Button, SegmentedControl, Divider, Box, Stack } from '@mantine/core'

// Цвета состояний сервисов
const DOT = { ok: '#40c057', warn: '#fab005', down: '#fa5252', off: '#868e96' }
const LBL = { ok: 'работает', warn: 'задержка', down: 'нет связи', off: 'выключен' }

function Dot({ state }) {
  const c = DOT[state] || DOT.off
  return (
    <span style={{
      width: 9, height: 9, borderRadius: '50%', background: c, flexShrink: 0,
      boxShadow: state === 'ok' ? `0 0 6px ${c}` : 'none',
    }} />
  )
}

function Service({ name, state, info, tip }) {
  return (
    <Tooltip label={tip} withArrow multiline w={250} position="top" openDelay={150}>
      <Group gap={6} wrap="nowrap" style={{ cursor: 'default' }}>
        <Dot state={state} />
        <Text size="xs" fw={600}>{name}</Text>
        {info != null && <Text size="xs" c="dimmed">{info}</Text>}
      </Group>
    </Tooltip>
  )
}

const fmtAge = (s) => (s == null ? '—' : s < 60 ? `${Math.round(s)}с` : `${Math.round(s / 60)}м`)

export default function StatusBar({ s = {}, online, mode, setMode, act, panic }) {
  const sv = s.services || {}
  const hl = sv.hyperliquid || {}
  const bn = sv.binance || {}
  const cp = sv.copier || {}
  const mn = sv.monitoring || {}

  // если бот недоступен — все сервисы неизвестны
  const off = (st) => (online ? st : 'down')

  // быстрый тумблер исполнения (тейкер/мейкер) — меняется на ходу
  const [exec, setExec] = useState(s.execution_mode || 'taker')
  useEffect(() => { if (s.execution_mode) setExec(s.execution_mode) }, [s.execution_mode])
  const changeExec = (v) => { setExec(v); act('/config', { execution_mode: v }) }

  const hlInfo = hl.transport === 'ws' ? `WS×${hl.ws_streams}` : 'REST'
  const bnInfo = bn.state === 'off' ? '—' : `${bn.network === 'mainnet' ? 'main' : bn.network || '?'}${bn.margin_ratio ? ` · MR ${bn.margin_ratio}%` : ''}`
  const cpInfo = !cp.running ? 'стоп' : `${cp.live ? 'LIVE' : 'DRY'} · ${cp.mode === 'ws' ? 'сокет' : 'опрос'} · ${cp.positions ?? 0} поз`
  const mnInfo = mn.state === 'off' ? '0' : `${mn.count} адр${mn.ws ? ' · WS' : ''}`

  const tips = {
    hl: `Hyperliquid — источник сигналов.\nТранспорт: ${hl.transport === 'ws' ? `WebSocket (${hl.ws_streams} потока)` : 'REST-опрос'}\nПоследний REST-ответ: ${fmtAge(hl.rest_age_sec)} назад\nСтатус: ${LBL[off(hl.state)]}`,
    bn: bn.state === 'off' ? 'Binance — ключи не заданы (бумажный режим)' : `Binance USDT-M — исполнение.\nСеть: ${bn.network}\nЭквити: $${bn.equity ?? '—'} · загрузка маржи ${bn.margin_ratio ?? 0}%\nПоследний ответ: ${fmtAge(bn.age_sec)} назад\nСтатус: ${LBL[off(bn.state)]}`,
    cp: `Копир — ${cp.running ? (cp.live ? 'боевой LIVE' : 'dry-run') : 'остановлен'}.\nРежим: ${cp.mode === 'ws' ? 'сокет (мгновенно)' : 'опрос'}${cp.ws != null ? ` · WS ${cp.ws ? 'подключён' : 'обрыв'}` : ''}\nОткрытых копий: ${cp.positions ?? 0}\nСтатус: ${LBL[off(cp.state)]}`,
    mn: mn.state === 'off' ? 'Монитор — нет наблюдаемых адресов' : `Монитор — ${mn.count} адрес(ов).\nWS-алерты: ${mn.ws ? 'активны (мгновенно)' : 'обрыв — работает страховка-опрос'}\nПоследнее событие: ${fmtAge(mn.last_event_sec)} назад\nСтатус: ${LBL[off(mn.state)]}`,
  }

  return (
    <Box style={{
      position: 'fixed', bottom: 0, left: 0, right: 0, height: 34, zIndex: 200,
      background: 'var(--mantine-color-dark-8, #141517)',
      borderTop: '1px solid var(--mantine-color-dark-4, #2c2e33)',
      padding: '0 14px',
    }}>
      <Group justify="space-between" h="100%" wrap="nowrap" gap="xs">
        <Group gap="lg" wrap="nowrap" style={{ overflow: 'hidden' }}>
          <Service name="Hyperliquid" state={off(hl.state)} info={hlInfo} tip={tips.hl} />
          <Service name="Binance" state={off(bn.state)} info={bnInfo} tip={tips.bn} />
          <Service name="Копир" state={off(cp.state)} info={cpInfo} tip={tips.cp} />
          <Service name="Монитор" state={off(mn.state)} info={mnInfo} tip={tips.mn} />
        </Group>

        <Group gap="sm" wrap="nowrap">
          <Text size="xs" fw={700}>{s.equity != null ? `$${s.equity}` : '—'}</Text>
          <Tooltip label="Документация (в новом табе)" withArrow>
            <ActionIcon variant="subtle" color="gray" size="sm" component="a"
              href="/docs" target="_blank" rel="noopener" aria-label="Документация">
              <span style={{ fontSize: 14 }}>📖</span>
            </ActionIcon>
          </Tooltip>
          <Popover width={240} position="top-end" withArrow shadow="md">
            <Popover.Target>
              <ActionIcon variant="subtle" color="gray" size="sm" aria-label="Быстрые настройки">
                <span style={{ fontSize: 14 }}>⚙️</span>
              </ActionIcon>
            </Popover.Target>
            <Popover.Dropdown>
              <Stack gap="xs">
                <Text size="xs" c="dimmed">Источник данных копира</Text>
                <Tooltip label="Опрос: раз в N сек. Сокет: мгновенно по сделкам (нужен .venv). Сменить можно только на остановленном боте." multiline w={230} withArrow>
                  <SegmentedControl size="xs" fullWidth value={mode} onChange={setMode} disabled={s.running}
                    data={[{ label: 'Опрос', value: 'poll' }, { label: 'Сокет', value: 'ws' }]} />
                </Tooltip>
                <Divider my={2} />
                <Text size="xs" c="dimmed">Исполнение ордеров</Text>
                <Tooltip label="Тейкер: рыночный, мгновенно. Мейкер: пассивная лимитка (GTX) у лучшей цены с фолбэком в тейкер — дешевле на альтах, медленнее. Можно менять на ходу." multiline w={230} withArrow>
                  <SegmentedControl size="xs" fullWidth value={exec} onChange={changeExec}
                    data={[{ label: 'Тейкер', value: 'taker' }, { label: 'Мейкер', value: 'maker' }]} />
                </Tooltip>
                <Divider my={2} />
                {!s.running ? (
                  <Group gap="xs" grow>
                    <Button size="xs" color="green" onClick={() => act('/start', { live: false, mode })}>Старт dry</Button>
                    <Button size="xs" color="orange" onClick={() => act('/start', { live: true, mode })}>Старт LIVE</Button>
                  </Group>
                ) : (
                  <Button size="xs" variant="default" onClick={() => act('/stop')}>Стоп копира</Button>
                )}
                <Button size="xs" color="red" variant="light" onClick={panic}>🚨 PANIC — закрыть всё</Button>
              </Stack>
            </Popover.Dropdown>
          </Popover>
        </Group>
      </Group>
    </Box>
  )
}
