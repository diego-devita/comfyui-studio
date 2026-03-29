# Chrome Extension Overview

The ComfyUI Studio Chrome extension (v1.1.0) is a Manifest V3 browser extension with two main functions:

1. **RunPod management** -- view billing, manage pods and storage, launch new pods from templates
2. **CivitAI integration** -- check model version status against your catalog, view image generation data, create presets from CivitAI images

The extension communicates with two APIs:

- **RunPod GraphQL API** (`api.runpod.io`) -- for pod and billing data
- **Studio backend API** (your pod URL) -- for catalog cross-referencing and preset creation

## Status Icon

The extension icon in the browser toolbar shows a colored bar indicating Studio connectivity:

- **Green bar** -- Studio backend is reachable and authenticated
- **Red bar** -- Studio backend is unreachable or authentication failed
- **No bar** -- Studio URL not configured

The status is checked when the popup opens by calling `GET /api/health` on the configured Studio URL.

## Architecture

The extension is a single-page popup (`popup.html`) with three tabs, all implemented in one JavaScript file (`popup.js`). It uses:

- `chrome.storage.local` for persisting API keys and the Studio URL
- `chrome.tabs` for detecting the current browser tab's URL (CivitAI page detection)
- Direct `fetch()` calls to RunPod and Studio APIs

## File Structure

```
chrome-extension/
├── src/                        Source files (load unpacked from here)
│   ├── manifest.json           Manifest V3 config
│   ├── popup.html              Main popup UI
│   ├── popup.js                All logic (RunPod, CivitAI, settings)
│   ├── popup.css               Styles
│   ├── icons.css               Font Awesome icons via CSS mask-image
│   └── icons/                  Extension icons (16/48/128px)
│       ├── icon*.png           Default icons
│       ├── icon*_connected.png Green-bar variants
│       └── icon*_disconnected.png Red-bar variants
├── dist/                       Pre-built ZIP for distribution
├── screens/                    Screenshots for Web Store listing
├── README.md                   Developer notes
└── STORE.md                    Web Store listing copy
```

## Permissions

The extension requests these permissions:

| Permission | Purpose |
|------------|---------|
| `storage` | Persist API keys and Studio URL across sessions |
| `tabs` | Read the active tab's URL to detect CivitAI pages |

Host permissions:

| Host | Purpose |
|------|---------|
| `https://api.runpod.io/*` | RunPod GraphQL API calls |
| `https://*.proxy.runpod.net/*` | Studio backend on RunPod pods |
| `https://civitai.com/*` | CivitAI page detection and API calls |
