# hl-copier-mcp

MCP-сервер для управления ботом **hl-copier** из AI-клиента (Claude Desktop, Claude Code, и т.п.).

Это тонкий клиент: он не импортирует код бота, а ходит по его REST API (по умолчанию
`http://127.0.0.1:8787`). Поэтому он работает независимо, переживает рестарты бота и
не трогает напрямую конфиг/ключи.

## Инструменты

**Только чтение:**
- `status` — эквити, открытые позиции (с ROI), режим LIVE/DRY, опрос/сокет, на связи ли бот
- `account_stats` — нереализованный PnL, плечо аккаунта, использование маржи, PnL за год
- `monitors` — наблюдаемые адреса с их позициями
- `position_history` — закрытые позиции на Binance (вход/выход/длительность/чистый PnL)
- `fills` — последние исполнения, с пометкой бот/ручное
- `logs` — лог бота (trade / skip / error / heartbeat)

**Управление (двигают реальные деньги — осознанно):**
- `start_copy(live=false)` — запустить копир (dry-run / боевой)
- `stop_copy` — остановить копир
- `panic` — 🚨 закрыть ВСЕ позиции и остановить
- `set_copy_target(address)` — сделать адрес единственной целью копирования

## Установка

```bash
cd hl-copier-mcp
python3.12 -m venv .venv
./.venv/bin/pip install -r requirements.txt
cp .env.example .env   # отредактируй при необходимости
```

`HLC_PASSWORD` нужен только если в боте включена авторизация UI (`auth_enabled`).
Если выключена — оставь пустым.

## Подключение к Claude

### Claude Desktop
В `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "hl-copier": {
      "command": "/Users/vladimirsizonenko/Documents/GitHub/это что за покемон/hl-copier-mcp/.venv/bin/python",
      "args": ["/Users/vladimirsizonenko/Documents/GitHub/это что за покемон/hl-copier-mcp/server.py"],
      "env": {
        "HLC_URL": "http://127.0.0.1:8787",
        "HLC_PASSWORD": ""
      }
    }
  }
}
```

### Claude Code (CLI)

```bash
claude mcp add hl-copier \
  -- "/Users/vladimirsizonenko/Documents/GitHub/это что за покемон/hl-copier-mcp/.venv/bin/python" \
     "/Users/vladimirsizonenko/Documents/GitHub/это что за покемон/hl-copier-mcp/server.py"
```

Бот (`hl-copier`) должен быть запущен (`tools/serve.py`), иначе инструменты вернут ошибку
подключения.
