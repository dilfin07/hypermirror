import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

// ---- чтение (live-данные с авто-рефетчем) ----
export const useServices = () => useQuery({ queryKey: ['services'], queryFn: api.services, refetchInterval: 5000 })
export const useLogs = () => useQuery({ queryKey: ['logs'], queryFn: api.logs, refetchInterval: 4000 })
export const useMonitors = () => useQuery({ queryKey: ['monitors'], queryFn: api.monitors, refetchInterval: 5000 })
export const useMeta = () => useQuery({ queryKey: ['meta'], queryFn: api.meta, refetchInterval: 5000 })
export const useAccounts = () => useQuery({ queryKey: ['accounts'], queryFn: api.accounts })
export const useTarget = () => useQuery({ queryKey: ['target'], queryFn: api.target, refetchInterval: 5000 })
export const useOverview = () => useQuery({ queryKey: ['overview'], queryFn: api.overview, refetchInterval: 5000 })
export const useJournal = () => useQuery({ queryKey: ['journal'], queryFn: api.journal, refetchInterval: 8000 })
export const useConfig = () => useQuery({ queryKey: ['config'], queryFn: api.config })

// ---- мутации (инвалидация → авто-рефетч соответствующего запроса) ----
export function useCopierControl() {
  const qc = useQueryClient()
  const inval = () => ['meta', 'services'].forEach((k) => qc.invalidateQueries({ queryKey: [k] }))
  const start = useMutation({ mutationFn: api.startBot, onSuccess: inval })
  const stop = useMutation({ mutationFn: api.stopBot, onSuccess: inval })
  return { start: start.mutate, stop: stop.mutate, starting: start.isPending, stopping: stop.isPending }
}

export function usePositionActions() {
  const qc = useQueryClient()
  // закрытие позиции меняет журнал/статус/эквити → инвалидируем их для авто-рефетча
  const inval = () => ['journal', 'meta', 'services', 'overview'].forEach((k) => qc.invalidateQueries({ queryKey: [k] }))
  const close = useMutation({ mutationFn: api.closePosition, onSuccess: inval })
  return { close: close.mutateAsync, closing: close.isPending }
}

export function useMonitorActions() {
  const qc = useQueryClient()
  const inval = () => qc.invalidateQueries({ queryKey: ['monitors'] })
  // смена цели меняет и цель, и (при clear) состояние бота → инвалидируем target/meta/services
  const invalCopy = () => { inval(); ['target', 'meta', 'services'].forEach((k) => qc.invalidateQueries({ queryKey: [k] })) }
  const setCopy = useMutation({ mutationFn: api.setCopyTarget, onSuccess: invalCopy })
  const clearCopy = useMutation({ mutationFn: api.clearCopyTarget, onSuccess: invalCopy })
  const toggleAlerts = useMutation({ mutationFn: (id) => api.toggleMonitor(id, 'alerts'), onSuccess: inval })
  const remove = useMutation({ mutationFn: api.removeMonitor, onSuccess: inval })
  const add = useMutation({ mutationFn: api.addMonitor, onSuccess: inval })
  return { setCopy: setCopy.mutate, clearCopy: clearCopy.mutate, toggleAlerts: toggleAlerts.mutate, remove: remove.mutate, add: add.mutate }
}

export function useSettingsActions() {
  const qc = useQueryClient()
  const inval = () => { qc.invalidateQueries({ queryKey: ['config'] }); qc.invalidateQueries({ queryKey: ['accounts'] }); qc.invalidateQueries({ queryKey: ['meta'] }) }
  return {
    saveConfig: useMutation({ mutationFn: api.saveConfig, onSuccess: inval }),
    saveTelegram: useMutation({ mutationFn: api.saveTelegram, onSuccess: inval }),
    testTelegram: useMutation({ mutationFn: api.testTelegram }),
    saveAuth: useMutation({ mutationFn: api.saveAuth, onSuccess: inval }),
    addAccount: useMutation({ mutationFn: api.addAccountKeys, onSuccess: inval }),
    deleteAccount: useMutation({ mutationFn: api.deleteAccount, onSuccess: inval }),
    switchActive: useMutation({ mutationFn: api.switchActive, onSuccess: inval }),
  }
}

export function useAccountActions() {
  const qc = useQueryClient()
  const inval = () => qc.invalidateQueries({ queryKey: ['accounts'] })
  const add = useMutation({ mutationFn: api.addAccount, onSuccess: inval })
  const remove = useMutation({ mutationFn: api.removeAccount, onSuccess: () => { inval(); qc.invalidateQueries({ queryKey: ['meta'] }) } })
  const setActive = useMutation({ mutationFn: api.setActiveAccount, onSuccess: () => qc.invalidateQueries({ queryKey: ['meta'] }) })
  return { add: add.mutate, remove: remove.mutate, setActive: setActive.mutate }
}
