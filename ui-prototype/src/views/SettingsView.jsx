import { useState, useEffect, useMemo } from 'react'
import {
  Group, Box, Stack, Title, UnstyledButton, Paper, Text, Badge, Button, Radio, Switch,
  SegmentedControl, NumberInput, Select, TextInput, PasswordInput, ActionIcon, Tooltip,
  TagsInput, Loader, Alert, useMantineColorScheme,
} from '@mantine/core'
import { Trash, Plus } from '@phosphor-icons/react'
import { CW, SECTIONS, TYPE_META } from '../constants'
import { Row, Section, ScopeBadge } from '../components/SettingsPrimitives'
import { useConfig, useSettingsActions } from '../api/queries'
import { usePrefs } from '../settings/prefs'
import { useT, TIMEZONES } from '../settings/i18n'

// кнопка сохранения config-секции + управляемый статус:
// есть изменения (оранж) → сохранено (на пару секунд) → пусто; кнопка активна только при изменениях
function SaveBar({ onSave, m, dirty, saved }) {
  const t = useT()
  return (
    <Group gap="sm" mt="md">
      <Button size="xs" onClick={onSave} loading={m.isPending} disabled={!dirty}>{t('set.save')}</Button>
      {m.isError ? <Text size="xs" c="red">{t('set.saveErr')}</Text>
        : dirty ? <Text size="xs" c="orange">● {t('set.dirty')}</Text>
        : saved ? <Text size="xs" c="teal">{t('set.saved')}</Text> : null}
    </Group>
  )
}

function ParamsPanel({ d, set, onSave, cfgM, dirty, saved }) {
  const t = useT()
  const skipOn = (d.start_skip_open ?? 'profitable') !== 'none'
  const acct = (d.accounts || []).find((a) => a.id === (d.active_account || 'main'))
  const acctLabel = acct?.label || d.active_account || 'Основной'
  return (
    <Box maw={720}>
      <Alert color="blue" variant="light" mb="lg" p="sm">
        <Text size="sm">{t('set.scopeNote.params')} <b>«{acctLabel}»</b> {t('set.scopeNote.paramsTail')}</Text>
      </Alert>
      <Section title={t('set.sec.exec')}>
        <Row label={t('set.orderMode')} hint={t('set.orderMode.hint')} scope="account">
          <SegmentedControl size="xs" w={CW} value={d.execution_mode || 'taker'} onChange={(v) => set('execution_mode', v)}
            data={[{ value: 'taker', label: t('set.taker') }, { value: 'maker', label: t('set.maker') }]} />
        </Row>
      </Section>
      <Section title={t('set.sec.lev')}>
        <Row label={t('set.levMode')} scope="account"><SegmentedControl size="xs" w={CW} value={d.leverage_mode || 'mirror'} onChange={(v) => set('leverage_mode', v)} data={['fixed', 'mirror']} /></Row>
        <Row label={t('set.mirrorCap')} scope="account"><NumberInput size="xs" w={CW} value={d.mirror_max_leverage ?? ''} onChange={(v) => set('mirror_max_leverage', v)} /></Row>
        <Row label={t('set.gross')} hint={t('set.gross.hint')} scope="account"><NumberInput size="xs" w={CW} value={d.leverage_cap ?? ''} onChange={(v) => set('leverage_cap', v)} /></Row>
        <Row label={t('set.multiplier')} hint={t('set.multiplier.hint')} scope="account"><NumberInput size="xs" w={CW} value={d.size_multiplier ?? 1} step={0.1} decimalScale={2} min={0} onChange={(v) => set('size_multiplier', v)} /></Row>
        <Row label={t('set.coinCap')} scope="account"><NumberInput size="xs" w={CW} value={d.max_notional_per_coin_usd ?? ''} onChange={(v) => set('max_notional_per_coin_usd', v)} thousandSeparator /></Row>
      </Section>
      <Section title={t('set.sec.coins')}>
        <Group gap={6}><Text size="sm" fw={500}>{t('set.whitelist')}</Text><ScopeBadge scope="account" /></Group>
        <Text size="xs" c="dimmed" mt={2} mb={8}>{t('set.whitelist.desc')}</Text>
        <TagsInput value={d.coin_whitelist || []} onChange={(v) => set('coin_whitelist', v.map((s) => s.trim().toUpperCase()).filter(Boolean))}
          placeholder={(d.coin_whitelist || []).length ? t('set.whitelist.add') : 'BTC, ETH…'} clearable maw={520}
          splitChars={[',', ' ']} styles={{ pill: { textTransform: 'uppercase' } }} />
      </Section>
      <Section title={t('set.sec.position')}>
        <Row label={t('set.propSpot')} hint={t('set.propSpot.hint')} scope="account"><Switch checked={d.proportion_include_spot !== false} onChange={(e) => set('proportion_include_spot', e.currentTarget.checked)} /></Row>
        <Row label={t('set.favGate')} hint={t('set.favGate.hint')} scope="account"><Switch checked={d.favorability_gate !== false} onChange={(e) => set('favorability_gate', e.currentTarget.checked)} /></Row>
        <Row label={t('set.favTol')} scope="account"><NumberInput size="xs" w={CW} value={d.favorability_tol_pct ?? ''} step={0.1} decimalScale={2} onChange={(v) => set('favorability_tol_pct', v)} /></Row>
        <Row label={t('set.autoSync')} hint={t('set.autoSync.hint')} scope="account"><Switch checked={!!d.auto_sync} onChange={(e) => set('auto_sync', e.currentTarget.checked)} /></Row>
        <Row label={t('set.manageOnly')} hint={t('set.manageOnly.hint')} scope="account"><Switch checked={!!d.manage_only_bot_positions} onChange={(e) => set('manage_only_bot_positions', e.currentTarget.checked)} /></Row>
        <Row label={t('set.freeze')} hint={t('set.freeze.hint')} scope="account">
          <Switch checked={skipOn} onChange={(e) => set('start_skip_open', e.currentTarget.checked ? 'profitable' : 'none')} />
        </Row>
        {skipOn && <Row label={t('set.profitThr')} scope="account"><NumberInput size="xs" w={CW} value={d.start_skip_profit_pct ?? ''} step={0.5} decimalScale={1} onChange={(v) => set('start_skip_profit_pct', v)} /></Row>}
      </Section>
      <Section title={t('set.sec.data')}>
        <Row label={t('set.source')} scope="global"><SegmentedControl size="xs" w={CW} value={d.data_mode || 'poll'} onChange={(v) => set('data_mode', v)} data={[{ value: 'poll', label: t('set.poll') }, { value: 'ws', label: t('set.socket') }]} /></Row>
        <Row label={t('set.pollInterval')} scope="global"><NumberInput size="xs" w={CW} value={d.poll_interval_sec ?? ''} onChange={(v) => set('poll_interval_sec', v)} /></Row>
        <Row label={t('set.copyTradfi')} hint={t('set.copyTradfi.hint')} scope="global">
          <Switch checked={d.skip_builder_dexs === false} onChange={(e) => set('skip_builder_dexs', !e.currentTarget.checked)} />
        </Row>
      </Section>
      <SaveBar onSave={onSave} m={cfgM} dirty={dirty} saved={saved} />
    </Box>
  )
}

function TelegramSection({ config, tg }) {
  const t = useT()
  const [on, setOn] = useState(!!config?.telegram?.enabled)
  const [token, setToken] = useState('')
  const [chat, setChat] = useState(config?.telegram?.chat_id || '')
  useEffect(() => { setOn(!!config?.telegram?.enabled); setChat(config?.telegram?.chat_id || '') }, [config])
  const save = () => tg.saveTelegram.mutate({ token, chat_id: chat, enabled: on }, { onSuccess: () => setToken('') })
  const test = () => tg.testTelegram.mutate()
  const tr = tg.testTelegram.data
  return (
    <Section title="Telegram">
      <Row label={t('set.tgAlerts')} hint={t('set.tgAlerts.hint')} scope="global">
        <Switch checked={on} onChange={(e) => setOn(e.currentTarget.checked)} />
      </Row>
      <Stack gap="sm" mt="xs" maw={520}>
        <Text size="xs" c="dimmed">{t('set.token')}: {config?.telegram?.has_token ? <Text span c="teal">{t('set.set')}</Text> : t('set.notSet')}</Text>
        <PasswordInput size="xs" label="Bot token" placeholder={t('set.botToken.ph')} value={token} onChange={(e) => setToken(e.currentTarget.value)} />
        <TextInput size="xs" label="Chat ID" placeholder={t('set.chatId.ph')} value={chat} onChange={(e) => setChat(e.currentTarget.value)} />
        <Group gap="sm" align="center">
          <Button size="xs" onClick={save} loading={tg.saveTelegram.isPending}>{t('set.saveTg')}</Button>
          <Button size="xs" variant="default" onClick={test} loading={tg.testTelegram.isPending} disabled={!on}>{t('set.test')}</Button>
          {tg.saveTelegram.isSuccess && <Text size="xs" c="teal">{t('set.saved')}</Text>}
          {tr && <Text size="xs" c={tr.ok ? 'teal' : 'red'}>{tr.ok ? t('set.testOk') : `${t('set.err')}: ${tr.info || ''}`}</Text>}
        </Group>
        <Text size="xs" c="dimmed">{t('set.tg.help')}</Text>
      </Stack>
    </Section>
  )
}

function AlertsPanel({ d, set, onSave, cfgM, dirty, saved, config, tg }) {
  const t = useT()
  return (
    <Box maw={720}>
      <Alert color="gray" variant="light" mb="lg" p="sm"><Text size="sm">{t('set.scopeNote.alerts')}</Text></Alert>
      <TelegramSection config={config} tg={tg} />
      <Section title={t('set.sec.antispam')}>
        <Row label={t('set.instant')} hint={t('set.instant.hint')} scope="global"><NumberInput size="xs" w={CW} value={d.monitor_instant_notional_usd ?? ''} onChange={(v) => set('monitor_instant_notional_usd', v)} thousandSeparator /></Row>
        <Row label={t('set.coalesce')} scope="global"><NumberInput size="xs" w={CW} value={d.monitor_coalesce_max_sec ?? ''} onChange={(v) => set('monitor_coalesce_max_sec', v)} /></Row>
        <Row label={t('set.quiet')} hint={t('set.quiet.hint')} scope="global"><NumberInput size="xs" w={CW} value={d.monitor_coalesce_quiet_sec ?? ''} onChange={(v) => set('monitor_coalesce_quiet_sec', v)} /></Row>
      </Section>
      <SaveBar onSave={onSave} m={cfgM} dirty={dirty} saved={saved} />
    </Box>
  )
}

function UiPanel() {
  const { scale, setScale, lang, setLang, tz, setTz } = usePrefs()
  const { colorScheme, setColorScheme } = useMantineColorScheme()
  const t = useT()
  return (
    <Box maw={720}>
      <Section title={t('ui.section.view')}>
        <Row label={t('ui.theme')}>
          <Radio.Group value={colorScheme === 'dark' ? 'dark' : 'light'} onChange={setColorScheme}>
            <Group gap="lg"><Radio value="light" label={t('ui.theme.light')} /><Radio value="dark" label={t('ui.theme.dark')} /></Group>
          </Radio.Group>
        </Row>
        <Row label={t('ui.scale')} hint={t('ui.scale.hint')}>
          <SegmentedControl size="xs" w={CW} value={String(scale)} onChange={(v) => setScale(Number(v))}
            data={[{ value: '0.8', label: 'S' }, { value: '0.9', label: 'M' }, { value: '1', label: 'L' }]} />
        </Row>
        <Row label={t('ui.lang')}>
          <Radio.Group value={lang} onChange={setLang}><Group gap="lg"><Radio value="ru" label="Русский" /><Radio value="en" label="English" /></Group></Radio.Group>
        </Row>
        <Row label={t('ui.tz')} hint={t('ui.tz.hint')}>
          <Select size="xs" w={CW} value={tz} onChange={(v) => v && setTz(v)} allowDeselect={false}
            data={TIMEZONES.map((z) => ({ value: z.value, label: z.label }))} />
        </Row>
      </Section>
    </Box>
  )
}

function AccessPanel({ config, actions }) {
  const t = useT()
  const [on, setOn] = useState(!!config?.auth_enabled)
  const [pw, setPw] = useState('')
  useEffect(() => { setOn(!!config?.auth_enabled) }, [config])
  const save = () => actions.saveAuth.mutate({ password: pw, enabled: on }, { onSuccess: () => setPw('') })
  return (
    <Box maw={720}>
      <Section title={t('set.sec.login')}>
        <Row label={t('set.requirePw')} hint={t('set.requirePw.hint')}><Switch checked={on} onChange={(e) => setOn(e.currentTarget.checked)} /></Row>
      </Section>
      <Section title={t('set.sec.password')}>
        <Text size="xs" c="dimmed" mb="xs">{t('set.sec.password')}: {config?.has_ui_password ? <Text span c="teal">{t('set.set')}</Text> : t('set.notSet')}</Text>
        <Group align="flex-end" gap="sm" maw={520}>
          <PasswordInput size="xs" style={{ flex: 1 }} label={t('set.newPw')} placeholder={t('set.newPw.ph')} value={pw} onChange={(e) => setPw(e.currentTarget.value)} />
          <Button size="xs" onClick={save} loading={actions.saveAuth.isPending}>{t('set.save')}</Button>
        </Group>
        {actions.saveAuth.isSuccess && <Text size="xs" c="teal" mt="xs">{t('set.accessUpdated')}</Text>}
        <Text size="xs" c="dimmed" mt="md" maw={560}>{t('set.access.help')}</Text>
      </Section>
    </Box>
  )
}

// относительное «когда счёт был активен в последний раз» (last_active с бэка, ts в секундах)
function relActive(ts, t) {
  if (!ts) return t('set.acc.never')
  const s = Math.floor(Date.now() / 1000 - ts)
  if (s < 90) return t('set.acc.now')
  if (s < 3600) return `${t('set.acc.ago')} ${Math.floor(s / 60)} ${t('set.acc.u.min')}`
  if (s < 86400) return `${t('set.acc.ago')} ${Math.floor(s / 3600)} ${t('set.acc.u.h')}`
  return `${t('set.acc.ago')} ${Math.floor(s / 86400)} ${t('set.acc.u.d')}`
}

function AccountCard({ a, active, onRemove }) {
  const t = useT()
  const isActive = a.id === active
  const tm = TYPE_META[a.type] || TYPE_META.futures
  return (
    <Paper withBorder p="md" w={258} radius="md" style={{ borderColor: isActive ? 'var(--mantine-color-blue-5)' : undefined, borderWidth: isActive ? 2 : 1 }}>
      <Group gap={8} wrap="nowrap" justify="space-between">
        <Text fw={600} size="sm" truncate>{a.label || a.id}</Text>
        {isActive && <Badge size="xs" color="blue" variant="filled" style={{ flexShrink: 0 }}>{t('set.accActive')}</Badge>}
      </Group>
      <Group gap={6} mt="sm" wrap="nowrap">
        <Badge size="xs" color={tm.color} variant="light">{t(`type.${a.type}`)}</Badge>
        <Badge size="xs" color={a.network === 'mainnet' ? 'red' : 'blue'} variant="light">{a.network}</Badge>
      </Group>
      <Text size="xs" c="dimmed" mt={8}>{relActive(a.lastActive, t)}</Text>
      <Group justify="space-between" mt="md" wrap="nowrap">
        <Text size="xs" c="dimmed" ff="monospace" truncate>{a.key_env}</Text>
        {a.id !== 'main' && <Tooltip label={t('set.deleteAccount')} withArrow><ActionIcon color="red" variant="subtle" size="sm" onClick={() => onRemove(a.id)}><Trash size={14} /></ActionIcon></Tooltip>}
      </Group>
    </Paper>
  )
}

function AddAccountForm({ onAdd, pending }) {
  const t = useT()
  const [type, setType] = useState('copy')
  const [label, setLabel] = useState('')
  const [prefix, setPrefix] = useState('')
  const [net, setNet] = useState('mainnet')
  const [key, setKey] = useState('')
  const [secret, setSecret] = useState('')
  const autoPrefix = prefix || `BINANCE_${(label || 'X').toUpperCase().replace(/[^A-Z0-9]+/g, '_')}`
  const id = (label || '').toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '') || 'acct'
  const submit = () => onAdd(
    { account: { id, label: label.trim(), key_env: autoPrefix, type, network: net }, api_key: key, api_secret: secret },
    () => { setLabel(''); setPrefix(''); setKey(''); setSecret('') },
  )
  return (
    <Paper withBorder p="md" radius="md" maw={760}>
      <Group grow>
        <Select size="xs" label={t('set.accType')} value={type} onChange={setType}
          data={[{ value: 'futures', label: t('set.accType.futures') }, { value: 'copy', label: t('set.accType.copy') }, { value: 'spot', label: t('set.accType.spot') }]} />
        <TextInput size="xs" label={t('set.label')} placeholder={t('set.label.ph')} value={label} onChange={(e) => setLabel(e.currentTarget.value)} />
        <Select size="xs" label={t('set.network')} value={net} onChange={setNet} data={['mainnet', 'testnet']} />
      </Group>
      <Group grow mt="sm">
        <TextInput size="xs" label={t('set.prefix')} placeholder={autoPrefix} value={prefix} onChange={(e) => setPrefix(e.currentTarget.value)} />
        <PasswordInput size="xs" label="API key" value={key} onChange={(e) => setKey(e.currentTarget.value)} />
        <PasswordInput size="xs" label="API secret" value={secret} onChange={(e) => setSecret(e.currentTarget.value)} />
      </Group>
      <Group justify="space-between" mt="md">
        <Text size="xs" c="dimmed">{t('set.keysGo')} <Text span ff="monospace">{autoPrefix}_API_KEY</Text></Text>
        <Button size="xs" leftSection={<Plus size={14} />} disabled={!label || !key || !secret} loading={pending} onClick={submit}>{t('set.addAccount')}</Button>
      </Group>
    </Paper>
  )
}

function KeysPanel({ config, actions }) {
  const t = useT()
  const accounts = config?.accounts || []
  const active = config?.active_account || 'main'
  return (
    <Box maw={900}>
      <Section title={t('set.sec.accounts')}>
        <Group gap="md" wrap="wrap" mt="xs" align="stretch">
          {accounts.map((a) => <AccountCard key={a.id} a={a} active={active} onRemove={(id) => actions.deleteAccount.mutate(id)} />)}
        </Group>
        <Text size="xs" c="dimmed" mt="sm">{t('set.accounts.hint')}</Text>
      </Section>
      <Section title={t('set.sec.addAcc')}>
        <AddAccountForm onAdd={(payload, reset) => actions.addAccount.mutate(payload, { onSuccess: reset })} pending={actions.addAccount.isPending} />
        {actions.addAccount.isSuccess && <Text size="xs" c="teal" mt="sm">{t('set.accAdded')}</Text>}
        {actions.addAccount.isError && <Text size="xs" c="red" mt="sm">{t('set.accAddErr')}</Text>}
      </Section>
    </Box>
  )
}

export default function SettingsView() {
  const [section, setSection] = useState('params')
  const t = useT()
  const label = (s) => t(`settings.section.${s.value}`)
  const cur = SECTIONS.find((s) => s.value === section)

  const { data: config } = useConfig()
  const actions = useSettingsActions()
  const [draft, setDraft] = useState(null)
  // ресинк черновика при загрузке и после каждого сохранения (config рефетчится по инвалидации)
  useEffect(() => { if (config) setDraft(config) }, [config])
  const set = (k, v) => setDraft((d) => ({ ...d, [k]: v }))
  // изменённые ключи vs загруженный эффективный конфиг (в оверрайды уйдёт только то, что менял)
  const patch = useMemo(() => {
    const p = {}
    if (draft && config) for (const k of Object.keys(draft)) {
      if (JSON.stringify(draft[k]) !== JSON.stringify(config[k])) p[k] = draft[k]
    }
    return p
  }, [draft, config])
  const dirty = Object.keys(patch).length > 0

  // «сохранено» — кратко после явного сохранения; гаснет через 2.5с, при правках и смене счёта/раздела
  const [saved, setSaved] = useState(false)
  const saveConfig = () => actions.saveConfig.mutate(patch, { onSuccess: () => setSaved(true) })
  useEffect(() => { if (dirty) setSaved(false) }, [dirty])
  useEffect(() => { setSaved(false); actions.saveConfig.reset() }, [config?.active_account, section]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (!saved) return; const id = setTimeout(() => setSaved(false), 2500); return () => clearTimeout(id) }, [saved])

  const needsConfig = section === 'params' || section === 'alerts' || section === 'keys' || section === 'access'

  return (
    <Group align="stretch" gap={0} h="100%" wrap="nowrap" style={{ overflow: 'hidden' }}>
      <Box w={250} p="sm" style={{ borderRight: '1px solid var(--mantine-color-default-border)', flexShrink: 0, height: '100%', overflowY: 'auto' }}>
        <Stack gap={2}>
          {SECTIONS.map((s) => {
            const Icon = s.icon
            const act = s.value === section
            return (
              <UnstyledButton key={s.value} onClick={() => setSection(s.value)}
                style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 10px', borderRadius: 8, fontSize: 14, fontWeight: act ? 600 : 500,
                  color: act ? 'var(--mantine-color-blue-light-color)' : 'light-dark(var(--mantine-color-gray-7), var(--mantine-color-gray-5))',
                  background: act ? 'var(--mantine-color-blue-light)' : 'transparent' }}>
                <Icon size={18} weight={act ? 'fill' : 'regular'} />{label(s)}
              </UnstyledButton>
            )
          })}
        </Stack>
      </Box>
      <Box style={{ flex: 1, height: '100%', overflowY: 'auto' }} p="lg">
        <Title order={3} mb="md">{cur && label(cur)}</Title>
        {needsConfig && !draft ? (
          <Group gap="xs" c="dimmed"><Loader size="sm" /><Text size="sm" c="dimmed">{t('set.loading')}</Text></Group>
        ) : (
          <>
            {section === 'params' && <ParamsPanel d={draft} set={set} onSave={saveConfig} cfgM={actions.saveConfig} dirty={dirty} saved={saved} />}
            {section === 'alerts' && <AlertsPanel d={draft} set={set} onSave={saveConfig} cfgM={actions.saveConfig} dirty={dirty} saved={saved} config={config} tg={actions} />}
            {section === 'ui' && <UiPanel />}
            {section === 'keys' && <KeysPanel config={config} actions={actions} />}
            {section === 'access' && <AccessPanel config={config} actions={actions} />}
          </>
        )}
      </Box>
    </Group>
  )
}
