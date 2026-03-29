# Telegram API

Endpoints for controlling the Telegram bot. All endpoints require authentication.

---

## GET /api/admin/telegram/status

Get the current Telegram bot status.

**Auth:** Required

**Response:** `200 OK`

```json
{
  "running": true,
  "name": "MyStudioBot",
  "started_at": "2026-03-30 14:30:00"
}
```

| Field | Description |
|-------|-------------|
| `running` | Whether the bot polling thread is alive |
| `name` | Bot name from `TELEGRAM_BOT_NAME` env var |
| `started_at` | Start timestamp in Italian timezone (Europe/Rome), or `null` if not running |

If `python-telegram-bot` is not installed:

```json
{
  "running": false,
  "name": "",
  "started_at": null,
  "error": "python-telegram-bot not installed"
}
```

---

## POST /api/admin/telegram/start

Start the Telegram bot.

**Auth:** Required

**Response:** `200 OK`

```json
{
  "result": "started"
}
```

Possible `result` values:

| Value | Meaning |
|-------|---------|
| `"started"` | Bot started successfully |
| `"already running"` | Bot was already running |
| `"no token configured"` | `TELEGRAM_BOT_TOKEN` is not set |

**Error:** `500 Internal Server Error` if `python-telegram-bot` is not installed.

---

## POST /api/admin/telegram/stop

Stop the Telegram bot.

**Auth:** Required

**Response:** `200 OK`

```json
{
  "result": "stopped"
}
```

Possible `result` values:

| Value | Meaning |
|-------|---------|
| `"stopped"` | Bot stopped |
| `"not running"` | Bot was not running |
