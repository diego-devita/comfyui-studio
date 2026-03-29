# Telegram Bot Configuration

## Required Settings

| Setting | Source | Description |
|---------|--------|-------------|
| `TELEGRAM_BOT_TOKEN` | Environment variable or Settings page | Bot token from [@BotFather](https://t.me/BotFather). Required. |
| `TELEGRAM_BOT_NAME` | Environment variable or Settings page | Display name for the bot (informational only). Optional. |

## Getting a Bot Token

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts to name your bot
3. BotFather gives you a token like `123456789:ABCdefGHI...`
4. Enter this token in the Settings page under the Telegram section, or set it as the `TELEGRAM_BOT_TOKEN` environment variable

## Setting the Token

### From the Settings Page

1. Go to **Settings** (`/admin/settings`)
2. Find the **Telegram** section
3. Enter the bot token
4. Click **Start** to start the bot

### As an Environment Variable

Set `TELEGRAM_BOT_TOKEN` when creating your RunPod pod or Docker container. The bot will auto-start on backend boot.

## Runtime Settings Storage

When edited from the Settings page, the token is persisted in both:

- `os.environ` (for the current process)
- The SQLite database (`database/studio.db` settings table) -- survives pod restarts

On subsequent boots, the backend loads saved settings from the database before `auto_start()` checks for the token.

## Bot Control Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /api/admin/telegram/status` | GET | Returns `{running, name, started_at}` |
| `POST /api/admin/telegram/start` | POST | Start the bot (returns `"started"`, `"already running"`, or `"no token configured"`) |
| `POST /api/admin/telegram/stop` | POST | Stop the bot |
