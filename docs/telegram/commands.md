# Telegram Bot Commands

## /start

Lists all public presets (where `private: false`) as inline keyboard buttons. Each button shows the preset's display name.

Also triggered by `/presets` and by sending any text message when not in the middle of a flow.

## Conversation Flow

After selecting a preset, the bot guides the user through a conversation:

### 1. Preset Selection

User taps a preset button. The bot shows:

- Preset name and description
- Associated workflow name

### 2. Placeholder Questions (if any)

If the preset's prompts contain [placeholders](../presets/placeholders.md), the bot asks each question in sequence:

- **Choice placeholders** (`[[question:opt1|opt2]]`) -- shown as inline keyboard buttons
- **Free text placeholders** (`[[question]]`) -- the bot asks the user to type their answer

Scene-based placeholders include the scene number (e.g., "Scena 1: style").

### 3. Photo Input

The bot asks the user to send a photo. The photo is used as the input image for the preset's workflow.

!!! note
    The bot always asks for a photo. For text-to-image presets that do not require an input image, the photo is sent but the workflow ignores it.

### 4. Confirmation

After receiving the photo, the bot shows a confirmation message with two buttons:

- **Launch** -- execute the job
- **Cancel** -- abort and clear the conversation state

### 5. Job Execution and Progress

After the user confirms:

1. The bot sends the preset to `POST /api/admin/presets/{id}/run` with the photo and placeholder answers
2. The bot displays "Uploading and queuing job..."
3. Every 10 seconds, the bot polls `GET /api/run/status/{prompt_id}`:
   - **Queued** -- "In coda -- waiting for execution slot..."
   - **Running** -- shows percentage, current node, and ETA
   - **Loading models** -- "Loading models..." (0% with no node)
4. On completion, the bot downloads the output file and sends it to the chat:
   - Video files (.mp4, .webm) are sent as Telegram video messages
   - Image files are sent as Telegram photo messages
   - The caption includes the preset name and seed value

### 6. Error Handling

- **Job failed/stalled/error** -- bot reports the error and clears state
- **Timeout** -- after 30 minutes (180 polls at 10s), the bot reports a timeout
- **API errors** -- reported with the first 200 characters of the error message
