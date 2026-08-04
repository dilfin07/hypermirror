import { useEffect, useState } from 'react'
import {
  Fieldset, Stack, Select, NumberInput, TagsInput, Button, Group,
  PasswordInput, Text, TextInput, ActionIcon, Tooltip, Switch, Radio, Badge, Code,
} from '@mantine/core'
import { getConfig, post } from '../api'

function L({ t, h }) {
  return (
    <span>
      {t}{' '}
      <Tooltip label={h} multiline w={280} withArrow position="top" events={{ hover: true, focus: true, touch: true }}>
        <Text span c="dimmed" style={{ cursor: 'help' }}>ⓘ</Text>
      </Tooltip>
    </span>
  )
}

const HELP = {
  leverage_mode: 'fixed — всегда твоё фикс. плечо. mirror — как у цели, но не выше потолка.',
  fixed_leverage: 'Плечо в режиме fixed. Применяется ко всем позициям независимо от цели.',
  mirror_max_leverage: 'Потолок плеча в режиме mirror. Если у цели 20x, а тут 5 — будет 5x.',
  leverage_cap: 'Максимальная суммарная экспозиция / эквити. Напр. 3 = не больше 3× депозита во всех позициях вместе.',
  max_notional: 'Максимальный размер ($) на одну монету. Ограничивает концентрацию в одном активе.',
  poll: 'Как часто опрашивать API в режиме «Опрос» (в режиме «Сокет» — фолбэк-интервал).',
  data_mode: 'poll — опрос API раз в N сек. ws — мгновенно по сделкам цели (нужен запуск через .venv/bin/python).',
  skip_open: 'profitable — не входить в уже открытые у цели позиции, что ушли в плюс ≥ порога. all — заморозить все открытые на старте. none — копировать всё текущее.',
  skip_pct: 'Порог «убежавшей» прибыли (движение цены от входа цели, %). Позиции выше — замораживаются на старте.',
  network: 'testnet — тренировочная сеть Binance (фейковые деньги). mainnet — реальные деньги.',
  whitelist: 'Только эти монеты копируются. Пусто = все монеты цели.',
  telegram: 'Бот-токен от @BotFather. chat_id — твой ID (узнать у @userinfobot) или ID группы. Шлём действия по позициям и ошибки.',
  fav_gate: 'Гейт «не добирать хуже цели». ВКЛ: доборы (доливы) пропускаются, если текущая цена хуже средней входа цели — чтобы наша средняя не стала хуже, чем у лида. Закрытия и сокращения проходят всегда. ВЫКЛ: зеркалим всё, включая усреднения против себя (макс. пропорция, макс. риск).',
  fav_tol: 'Допуск гейта, %. Насколько хуже входа цели мы ещё согласны добирать. 0.3 = терпим доборы до 0.3% хуже, дальше режем. Выше (0.5–1%) — реже отсекаем (точнее пропорция, но входим хуже). Ниже к 0 — строже (бережёт среднюю, но сильнее недонабираем).',
}

export default function Settings() {
  const [c, setC] = useState(null)
  const [key, setKey] = useState('')
  const [secret, setSecret] = useState('')
  // форма «Добавить счёт»
  const [addType, setAddType] = useState('futures')
  const [addLabel, setAddLabel] = useState('')
  const [addPrefix, setAddPrefix] = useState('')
  const [addNet, setAddNet] = useState('mainnet')
  const [tgEnabled, setTgEnabled] = useState(false)
  const [tgChat, setTgChat] = useState('')
  const [tgToken, setTgToken] = useState('')
  const [authEnabled, setAuthEnabled] = useState(false)
  const [uiPw, setUiPw] = useState('')
  const [msg, setMsg] = useState('')

  const load = async () => {
    const cfg = await getConfig()
    setC(cfg)
    setTgEnabled(cfg.telegram?.enabled || false)
    setTgChat(cfg.telegram?.chat_id || '')
    setAuthEnabled(cfg.auth_enabled || false)
  }
  useEffect(() => { load() }, [])
  if (!c) return <Text>Загрузка…</Text>

  const upd = (k, v) => setC({ ...c, [k]: v })
  const save = async () => { await post('/config', c); setMsg('Настройки сохранены'); load() }
  // завести счёт: тип+метка+префикс+сеть + ключи (создаёт профиль и пишет ключи в его префикс)
  const addAccount = async () => {
    const id = (addLabel || '').toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '') || `acct${(c.accounts || []).length}`
    const key_env = (addPrefix || `BINANCE_${id.toUpperCase().replace(/-/g, '_')}`).trim()
    const acc = { id, label: addLabel.trim(), key_env, type: addType, network: addNet }
    const others = (c.accounts || []).filter((a) => a.key_env !== key_env && a.id !== id)
    await post('/config', { ...c, accounts: [...others, acc] })   // создаём/обновляем профиль
    await post('/keys', { api_key: key, api_secret: secret, key_env })   // ключи в его префикс
    setKey(''); setSecret(''); setAddLabel(''); setAddPrefix('')
    setMsg(`Счёт «${acc.label || id}» добавлен (${key_env})`); load()
  }
  const saveTg = async () => { await post('/telegram', { token: tgToken, chat_id: tgChat, enabled: tgEnabled }); setTgToken(''); setMsg('Telegram сохранён'); load() }
  const testTg = async () => { const r = await post('/telegram_test', {}); setMsg(r.ok ? 'Тест отправлен ✓' : `Ошибка: ${r.info}`) }
  const saveAuth = async () => { await post('/ui_auth', { password: uiPw, enabled: authEnabled }); setUiPw(''); setMsg('Доступ обновлён'); load() }
  const setT = (i, k, v) => { const t = [...c.targets]; t[i] = { ...t[i], [k]: v }; upd('targets', t) }
  const addT = () => upd('targets', [...(c.targets || []), { address: '', weight: 1, label: '' }])
  const delT = (i) => upd('targets', c.targets.filter((_, j) => j !== i))
  const delA = (i) => upd('accounts', c.accounts.filter((_, j) => j !== i))
  const switchActive = async (id) => {
    const r = await post('/active_account', { id })
    if (r.error) { setMsg('⚠️ ' + r.error); return }      // отказ (бот запущен / есть позиция) — не переключаем
    setMsg(`Активный счёт переключён${r.type ? ' · ' + r.type : ''}`); load()
  }

  return (
    <Stack>
      <Fieldset legend="Плечо и риск">
        <Group grow>
          <Select label={<L t="Режим плеча" h={HELP.leverage_mode} />} data={['fixed', 'mirror']} value={c.leverage_mode} onChange={(v) => upd('leverage_mode', v)} />
          <NumberInput label={<L t="Fixed плечо" h={HELP.fixed_leverage} />} value={c.fixed_leverage} onChange={(v) => upd('fixed_leverage', v)} />
          <NumberInput label={<L t="Mirror потолок" h={HELP.mirror_max_leverage} />} value={c.mirror_max_leverage} onChange={(v) => upd('mirror_max_leverage', v)} />
        </Group>
        <Group grow mt="sm">
          <NumberInput label={<L t="Gross кэп (×эквити)" h={HELP.leverage_cap} />} value={c.leverage_cap} onChange={(v) => upd('leverage_cap', v)} />
          <NumberInput label={<L t="Кэп $/монета" h={HELP.max_notional} />} value={c.max_notional_per_coin_usd} onChange={(v) => upd('max_notional_per_coin_usd', v)} />
          <Select label={<L t="Источник данных" h={HELP.data_mode} />} data={[{ value: 'poll', label: 'Опрос' }, { value: 'ws', label: 'Сокет' }]} value={c.data_mode} onChange={(v) => upd('data_mode', v)} />
        </Group>
        <Group grow mt="sm">
          <NumberInput label={<L t="Опрос, сек" h={HELP.poll} />} value={c.poll_interval_sec} onChange={(v) => upd('poll_interval_sec', v)} />
          <Select label={<L t="Скип на старте" h={HELP.skip_open} />} data={['profitable', 'all', 'none']} value={c.start_skip_open} onChange={(v) => upd('start_skip_open', v)} />
          <NumberInput label={<L t="Порог профита, %" h={HELP.skip_pct} />} value={c.start_skip_profit_pct} onChange={(v) => upd('start_skip_profit_pct', v)} />
        </Group>
        <Group grow mt="sm">
          <Select label={<L t="Сеть Binance" h={HELP.network} />} data={['testnet', 'mainnet']} value={c.binance_network} onChange={(v) => upd('binance_network', v)} />
        </Group>
      </Fieldset>

      <Fieldset legend="Набор позиции (favorability-гейт)">
        <Group grow align="flex-start">
          <Switch label={<L t="Гейт «не добирать хуже цели»" h={HELP.fav_gate} />}
                  checked={c.favorability_gate !== false}
                  onChange={(e) => upd('favorability_gate', e.currentTarget.checked)} />
          <NumberInput label={<L t="Допуск, %" h={HELP.fav_tol} />}
                  value={c.favorability_tol_pct} step={0.1} min={0} decimalScale={2}
                  disabled={c.favorability_gate === false}
                  onChange={(v) => upd('favorability_tol_pct', v)} />
        </Group>
        <Text size="xs" c="dimmed" mt={8}>
          <b>Зачем.</b> Лид может усреднять позицию против себя (добирать по худшей цене) — у него
          кэш-буфер держит риск (плечо ~0.7×). У нас буфера нет, поэтому на таких доборах гейт
          <b> придерживает</b>, чтобы наша средняя не стала хуже, чем у лида. Плата за это — слегка
          <b> недонабираем</b> пропорцию (наш размер чуть меньше полного).
        </Text>
        <Text size="xs" c="dimmed" mt={4}>
          <b>Как двигать.</b> Допуск <b>ниже</b> (→0) = строже: бережём среднюю, чаще пропускаем
          доборы. <b>Выше</b> (0.5–1%) = мягче: точнее повторяем размер, но входим хуже цены лида.
          Гейт <b>выкл</b> = повторяем всё, включая усреднения вниз (макс. пропорция и макс. риск).
        </Text>
      </Fieldset>

      <Fieldset legend={<L t="Пары (вайтлист)" h={HELP.whitelist} />}>
        <TagsInput value={c.coin_whitelist || []} onChange={(v) => upd('coin_whitelist', v)} placeholder="BTC, ETH, HYPE…" />
      </Fieldset>

      <Fieldset legend="Цели копирования">
        {(c.targets || []).map((t, i) => (
          <Group key={i} mt={i ? 'xs' : 0} wrap="nowrap">
            <TextInput style={{ flex: 1 }} placeholder="0x адрес" value={t.address} onChange={(e) => setT(i, 'address', e.currentTarget.value)} />
            <TextInput w={160} placeholder="метка" value={t.label} onChange={(e) => setT(i, 'label', e.currentTarget.value)} />
            <NumberInput w={90} placeholder="вес" value={t.weight} step={0.1} onChange={(v) => setT(i, 'weight', v)} />
            <Tooltip label="Открыть на Hyperdash" withArrow>
              <ActionIcon variant="light" color="blue" component="a" disabled={!t.address}
                href={t.address ? `https://hyperdash.com/address/${t.address}` : undefined} target="_blank" rel="noreferrer">↗</ActionIcon>
            </Tooltip>
            <ActionIcon color="red" variant="light" onClick={() => delT(i)}>✕</ActionIcon>
          </Group>
        ))}
        <Button variant="light" size="xs" mt="sm" onClick={addT}>+ цель</Button>
      </Fieldset>

      <Fieldset legend="Счета — активный (переключение)">
        <Text size="xs" c="dimmed" mb="xs">
          Заведённые счета. Точка слева — <b>активный</b> (на нём торгует бот). Завести новый — блок ниже.
          <b> Переключать можно только на остановленном боте и при флэте</b> (иначе позиция на текущем счёте осиротеет).
        </Text>
        <Radio.Group value={c.active_account || 'main'} onChange={switchActive}>
          {(c.accounts || []).map((a, i) => (
            <Group key={i} mt={i ? 8 : 0} wrap="nowrap" align="center">
              <Tooltip label="Сделать активным" withArrow><Radio value={a.id} /></Tooltip>
              <Text fw={500} w={200} truncate>{a.label || a.id}</Text>
              <Badge size="sm" color={a.type === 'copy' ? 'grape' : a.type === 'spot' ? 'cyan' : 'gray'}>
                {a.type === 'copy' ? 'копи-портфель' : a.type === 'spot' ? 'спот' : 'фьючерсы'}
              </Badge>
              <Badge size="sm" color={a.network === 'mainnet' ? 'red' : 'blue'}>{a.network}</Badge>
              <Code>{a.key_env}</Code>
              <div style={{ flex: 1 }} />
              <ActionIcon color="red" variant="light" onClick={() => delA(i)} disabled={a.id === 'main'} title="Удалить счёт">✕</ActionIcon>
            </Group>
          ))}
        </Radio.Group>
      </Fieldset>

      <Fieldset legend="Добавить счёт (API)">
        <Text size="xs" c="dimmed" mb="xs">
          Заведи счёт: выбери <b>тип</b> (у API есть различия — копи-портфель: отдельный кошелёк, whitelist
          символов, ниже рейт-лимит), дай метку и ключи. env-префикс подставится сам (можно поправить).
          Ключи лягут в <code>{(addPrefix || `BINANCE_${(addLabel || 'X').toUpperCase().replace(/[^A-Z0-9]+/g, '_')}`)}_API_KEY</code>.
        </Text>
        <Group grow>
          <Select label="Тип счёта" data={[{ value: 'futures', label: 'Фьючерсы (USDT-M)' }, { value: 'copy', label: 'Копи-портфель (lead)' }, { value: 'spot', label: 'Спот' }]} value={addType} onChange={setAddType} />
          <TextInput label="Метка" placeholder="напр. Копи · ASTER" value={addLabel} onChange={(e) => setAddLabel(e.currentTarget.value)} />
          <Select label="Сеть" data={['mainnet', 'testnet']} value={addNet} onChange={setAddNet} />
        </Group>
        <Group grow mt="sm">
          <TextInput label="env-префикс ключей (авто, можно поправить)" placeholder="BINANCE_COPY_ASTER" value={addPrefix} onChange={(e) => setAddPrefix(e.currentTarget.value)} />
          <PasswordInput label="API key" value={key} onChange={(e) => setKey(e.currentTarget.value)} />
          <PasswordInput label="API secret" value={secret} onChange={(e) => setSecret(e.currentTarget.value)} />
        </Group>
        <Button mt="sm" size="xs" onClick={addAccount} disabled={!addLabel || !key || !secret}>Добавить счёт</Button>
        <Text size="xs" c="dimmed" mt={6}>Текущий «Основной» (BINANCE) {c.has_keys ? <Text span c="teal">— ключи заданы ✓</Text> : '— ключей нет'}. Чтобы обновить его ключи — заведи с префиксом <code>BINANCE</code>.</Text>
      </Fieldset>

      <Fieldset legend={<L t="Telegram-алерты" h={HELP.telegram} />}>
        <Group justify="space-between">
          <Switch label="Включить алерты" checked={tgEnabled} onChange={(e) => setTgEnabled(e.currentTarget.checked)} />
          <Text size="xs" c="dimmed">Токен: {c.telegram?.has_token ? <Text span c="teal">задан ✓</Text> : 'не задан'}</Text>
        </Group>
        <Group grow mt="sm">
          <TextInput label="chat_id" placeholder="напр. 123456789" value={tgChat} onChange={(e) => setTgChat(e.currentTarget.value)} />
          <PasswordInput label="Bot token" placeholder="от @BotFather (оставь пустым — не менять)" value={tgToken} onChange={(e) => setTgToken(e.currentTarget.value)} />
        </Group>
        <Group mt="sm">
          <Button size="xs" onClick={saveTg}>Сохранить Telegram</Button>
          <Button size="xs" variant="default" onClick={testTg} disabled={!c.telegram?.enabled && !tgEnabled}>Тест отправки</Button>
        </Group>
        <Text size="xs" c="dimmed" mt={6}>Шлём действия по позициям (открыл/долил/сократил/закрыл) и ошибки.</Text>
        <Text size="xs" c="dimmed" mt={4}>
          <b>Управление из Telegram</b> (команды только из твоего чата): /status · /live · /dry · /stop · /panic · /restart · /help
        </Text>
      </Fieldset>

      <Fieldset legend="Доступ (логин в UI)">
        <Group justify="space-between">
          <Switch label="Требовать пароль для входа" checked={authEnabled} onChange={(e) => setAuthEnabled(e.currentTarget.checked)} />
          <Text size="xs" c="dimmed">Пароль: {c.has_ui_password ? <Text span c="teal">задан ✓</Text> : 'не задан'}</Text>
        </Group>
        <PasswordInput mt="sm" label="Новый пароль (пусто — не менять)" placeholder="UI пароль" value={uiPw} onChange={(e) => setUiPw(e.currentTarget.value)} />
        <Button mt="sm" size="xs" onClick={saveAuth} disabled={authEnabled && !c.has_ui_password && !uiPw}>Сохранить доступ</Button>
        <Text size="xs" c="dimmed" mt={6}>
          Для локалхоста можно не включать. Включай, когда UI станет доступен в сети (напр. на Raspberry Pi).
          Защищает только UI/API — канал шифруй отдельно (Tailscale / TLS).
        </Text>
      </Fieldset>

      <Group>
        <Button onClick={save}>Сохранить настройки</Button>
        {msg && <Text c="teal" size="sm">{msg}</Text>}
      </Group>
    </Stack>
  )
}
