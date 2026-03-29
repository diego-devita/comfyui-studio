# Installation

## From the Settings Page (Recommended)

The easiest way to get the extension is to download it from your Studio instance:

1. Log in to your ComfyUI Studio instance
2. Go to **Settings** (`/admin/settings`)
3. Click the **Download Chrome Extension** button
4. Extract the downloaded ZIP file
5. Open Chrome and go to `chrome://extensions`
6. Enable **Developer mode** (toggle in the top right)
7. Click **Load unpacked** and select the extracted folder

The download endpoint packages the extension source files from `chrome-extension/src/` into a ZIP.

## From Source

If you have the repository cloned:

1. Open Chrome and go to `chrome://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked**
4. Select the `chrome-extension/src/` directory from the repository

## Initial Configuration

After installing, click the extension icon in the toolbar and go to the **Settings** tab:

1. **RunPod API Key** -- get from [runpod.io/console/user/settings](https://www.runpod.io/console/user/settings). Required for the RunPod tab.
2. **Studio URL** -- your pod's URL, e.g., `https://abcdef-8000.proxy.runpod.net`. Required for CivitAI features.
3. **Studio API Key** -- the same password you use to log in to Studio. Required for CivitAI features.

Settings are saved to Chrome's local storage and persist across browser restarts.
