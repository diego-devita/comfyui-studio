# Chrome Extension Changelog

## v3.0.0 — 2026-03-31 12:25
- **BREAKING: Side panel only** — popup removed, extension icon opens/closes side panel directly
- Background service worker with `openPanelOnActionClick: true`
- **New permission**: `background` service worker
- Minimum width overlay: ⛔ forbidden screen when panel < 680px with live width display
- Width indicator in status bar: appears during resize, fades after 5s
- Header tabs and studio status hidden when panel too narrow

## v2.1.0 — 2026-03-31 11:39
- Studio connection badge in header: Online (green border, clickable link) / Offline (red border)
- Hover: colored background fill with tooltip ("Clicca per visitare..." / "Istanza non collegata")
- Changelog viewer: click version number in bottom bar to view rendered changelog
- CHANGELOG.md bundled in extension source

## v2.0.0 — 2026-03-31 11:13
- **Side Panel mode**: click ⧉ icon to detach popup into a persistent side panel that stays open when switching tabs/windows
- **New permissions**: `sidePanel` (side panel API), `activeTab` (detect current tab URL in side panel)
- Side panel auto-refreshes CivitAI detection when navigating or switching tabs
- CivitAI tab: retry studio connection check if not ready on first load
- Settings save now properly awaits init before refreshing CivitAI tab

## v1.3.0 — 2026-03-31 10:53
- Status banner moved to fixed bottom bar (no more layout shift)
- Progress bar on status banner with 6s countdown
- Retry progress bar: single-timer system (100ms tick), smooth CSS transition, no sync issues
- GPU name styled as purple badge
- Network volume shown on pod card with gray badge
- Pod card row layout: flex with 1em gap
- Popup width increased to 680px
- GPU unavailable detection: matches multiple RunPod error messages
- Launch retry: interval dropdown (5s–30s), launch button disabled during retry
- Status banner flash effect on every new message
- Pod card: title margin-bottom 8px, meta row padding 4px 6px

## v1.2.0 — 2026-03-30 22:02
- Auto-retry on pod launch when GPU unavailable
- Shows retry bar with elapsed timer and attempt count
- Stop button to cancel retry
- Same retry system for both resume and launch

## v1.1.0 — 2026-03-29 22:25
- Tab UI: RunPod | CivitAI | Settings (header tabs)
- CivitAI model pages: version list with catalog cross-reference, +Add, Download
- CivitAI image pages: resources + detected deps, generation settings, Create Preset
- Auto-detects CivitAI pages via chrome.tabs.query
- Icon status: green/red bottom bar for connected/disconnected
- Wider popup (580px)

## v1.0.0 — 2026-03-29 08:48
- Initial release
- RunPod pod management: billing, pods, storage
- Launch pod with GPU sort, favorites, region, volume, template selection
- Find running pod button in settings
- Toggle API key visibility
- Settings persistence via chrome.storage
