# Pages

ComfyUI Studio has 11 pages accessible from the navigation bar and URL routing.

- [Home](home.md) — dashboard with versions, telemetry, update controls
- [Model Manager](models.md) — download and manage AI models
- [LoRA Manager](loras.md) — style LoRA catalog
- [LLM Assistant](llm.md) — local LLM models, chat
- [Workflow Manager](workflows.md) — browse and check workflow readiness
- [Job Queue](queue.md) — real-time progress tracking
- [Job History](history.md) — past generations, retry, export
- [Asset Manager](assets.md) — input/output file browser
- [Settings](settings.md) — configuration
- [Workflow Runner](runner.md) — execute workflows through forms

## Global UI Elements

Every page includes:

### Navigation Bar
Top bar with links to all pages. Includes:
- **Gear icon** → Settings page
- **Bell icon** → Activity Panel (dropdown)

### Activity Panel
Drops down from the bell icon in the nav. Shows:
- Live events from the EventBus via WebSocket
- Connection status dot (green = connected, red = disconnected)
- Event list with timestamps, severity colors, and messages

### Toast Notifications
Stacked notifications in the bottom-right corner. Each toast has:
- A message
- A severity color (info=blue, success=green, warning=yellow, error=red)
- An expiry progress bar that counts down
- Auto-dismiss after timeout (configurable per toast)

No `alert()` calls anywhere in the application. All notifications use `showToast()`.

### Confirm Dialogs
Native HTML `<dialog>` elements. Replace all `confirm()` calls with `studioConfirm()` which returns a Promise. Shows a styled modal with a message and OK/Cancel buttons.

### Icons
Font Awesome 6 Free icons rendered via CSS `mask-image` technique. The icon CSS classes are defined in `frontend/css/icons.css`. No JavaScript font loading or SVG sprites — pure CSS.
