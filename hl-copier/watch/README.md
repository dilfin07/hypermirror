# Локальный сторож копира (watchdog)

Заменяет прежний AI-`/loop` присмотр: та же логика порогов, но **ноль токенов**,
крутится прямо на Pi по systemd-таймеру, переживает закрытие Claude Code.

**Только алерт.** Скрипт никогда не трогает деньги/позиции — читает `/api/status` +
`/api/logs`, классифицирует, шлёт текст в TG через `/api/notify` бота. Дедуп по
`runtime/watchdog_state.json` — сообщение уходит только на смену состояния.

## Установка на Pi (один раз)

Файлы приезжают с `deploy.sh`. Дальше на Pi поставить user-таймер:

```bash
mkdir -p ~/.config/systemd/user
ln -sf ~/hl-copier/watch/hl-watchdog.service ~/.config/systemd/user/hl-watchdog.service
ln -sf ~/hl-copier/watch/hl-watchdog.timer   ~/.config/systemd/user/hl-watchdog.timer
systemctl --user daemon-reload
systemctl --user enable --now hl-watchdog.timer
loginctl enable-linger "$USER"   # чтобы таймер шёл без активной сессии
```

Проверка:

```bash
systemctl --user list-timers hl-watchdog.timer
systemctl --user start hl-watchdog.service   # прогнать разово сейчас
journalctl --user -u hl-watchdog.service -n 20
```

## Настройка

Порог интервала — в `hl-watchdog.timer` (`OnUnitActiveSec`).
Переменные окружения (необязательно): `HLC_URL` (умолч. `http://127.0.0.1:8787`),
`HLC_PASSWORD` (если включена авторизация UI). Кладутся в `[Service]` как `Environment=`.
