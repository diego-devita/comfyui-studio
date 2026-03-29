# Telegram Bot Overview

The Telegram bot is an optional component that runs as a daemon thread inside the Studio backend process. It uses the `python-telegram-bot` library with manual polling (not webhooks) and communicates with the Studio backend via localhost HTTP calls.

## Architecture

The bot runs in a background thread with its own asyncio event loop. This is necessary because the main thread runs uvicorn's async event loop, and `python-telegram-bot`'s `run_polling()` requires the main thread. The solution:

1. A daemon thread is created with `threading.Thread(daemon=True)`
2. The thread creates a new `asyncio.event_loop`
3. The bot application is built and handlers are registered
4. Manual polling starts: `initialize() -> start() -> updater.start_polling()`
5. The polling loop runs until `_bot_started_at` is set to `None` (stop signal)

## Communication with Studio

The bot does not import or call Studio backend functions directly. Instead, it makes HTTP requests to `http://127.0.0.1:{STUDIO_PORT}` with an `X-API-Key` header, using the same API that external clients use. This keeps the bot fully decoupled from the backend internals.

API calls used by the bot:

| Endpoint | Purpose |
|----------|---------|
| `GET /api/admin/presets` | List available presets |
| `GET /api/admin/presets/{id}` | Get preset details |
| `GET /api/admin/presets/{id}/placeholders` | Extract placeholder questions |
| `POST /api/admin/presets/{id}/run` | Execute a preset |
| `GET /api/run/status/{prompt_id}` | Poll job progress |
| `GET /api/comfyui/view` | Download the result file |

## Auto-start

On backend startup, `telegram_bot.auto_start()` is called. If `TELEGRAM_BOT_TOKEN` is set in the environment (or in the database settings), the bot starts automatically. If the token is not set, the bot remains stopped and can be started later from the Settings page.

## Dependencies

The bot requires the `python-telegram-bot` package. If the package is not installed, the bot control endpoints return an error message instead of crashing the backend.
