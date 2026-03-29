# Settings Tab

The Settings tab stores the API keys and URLs needed by the extension.

## Configuration Fields

| Field | Purpose | Required For |
|-------|---------|-------------|
| **RunPod API Key** | Authenticates with the RunPod GraphQL API | RunPod tab (billing, pods, storage, launch) |
| **Studio URL** | The full URL of your Studio instance (e.g., `https://abc-8000.proxy.runpod.net`) | CivitAI tab features |
| **Studio API Key** | The same `API_KEY` password used to log in to Studio | CivitAI tab features |

## Key Visibility

API keys are stored in `chrome.storage.local` and shown as password fields by default. Each key field has a toggle button to reveal/hide the value.

## Persistence

Settings are saved to Chrome's local storage when the Save button is clicked. They persist across browser restarts and extension updates. They are not synced across devices (local storage only, not `chrome.storage.sync`).

## Connection Status

After saving settings, the extension checks connectivity to the Studio backend by calling `GET /api/health`. The status dot in the header updates:

- **Green** -- Studio reachable and responding
- **Red** -- connection failed

The Studio link arrow (`->`) in the header becomes visible and clickable when a Studio URL is configured, opening the Studio web UI in a new tab.
