# Changelog

## v26.3.0 — 2026-03-31 05:49
- New workflow: WAN 2.2 SVI Pro Multi-Scene HD with RealESRGAN 2x upscale (~480p → ~960p)

## v26.2.0 — 2026-03-31 05:08
- Pipeline auto-detects NSFW content from image description + scene prompts and adds nsfw-general LoRA (str 0.9)

## v26.1.1 — 2026-03-31 04:23
- Zoom-reveal LoRA strength set to 0.8 per creator recommendation

## v26.1.0 — 2026-03-31 03:53
- Pipeline parses `LORAS:` line from Multiscena LLM output
- Zoom-reveal LoRA auto-mapped to high+low safetensors files
- NSFW models added to catalog: Midnight Miqu 70B, Darkest Universe 29B, Stheno 8B
- Added `nsfw` tag to all abliterated models
- Catalog filters: Tags row (NSFW / Non-NSFW), family toggles for new models
- Pipeline text_model requirement supports multiple alternative models (dropdown to select)
- Language reminder appended to scene generation prompt

## v25.6.1 — 2026-03-31 02:45
- Fixed scenes=0 (auto) being converted to 4 by JS falsy check
- Multiscena system prompt updated on pod: lighting, framing, movement rules

## v25.6.0 — 2026-03-31 02:31
- Pipeline History tab: list past runs with thumbnail, status, date
- Detail view: input image, description, scenes, Build with AI conversation, job link, full log
- Build with AI chat history saved in pipeline inputs for persistence

## v25.5.0 — 2026-03-31 02:19
- Streaming token-by-token on Chat tab and Build with AI
- Fixed SSE proxy: double newline separator, filter empty lines

## v25.4.0 — 2026-03-31 02:05
- Scenes field: 0 = auto (Multiscena LLM decides optimal count, no max)
- Build with AI: inline mini-chat in pipeline form using Prompt Builder preset
- Extracts `PROMPT:` line into textarea automatically
- Pipeline text_model min_ctx raised to 32768

## v25.3.0 — 2026-03-31 01:48
- Pipeline runs persisted in `pipeline_runs` DB table with full log, inputs, image reference
- Delete conversation button (✕) on each chat in sidebar with confirmation
- Removed model filter dropdown from chat sidebar
- Pipeline logs constructed prompt with scene count before sending to LLM

## v25.2.0 — 2026-03-31 01:29
- Description field on chat presets (editable in dialog, visible in sidebar and dropdown)
- Auto-migration for existing DBs

## v25.1.1 — 2026-03-31 01:02
- Pipeline auth reads API_KEY from os.environ (set by events.py boot from DB)
- Image analyzer message explicitly asks for age assessment with aging indicators
- Live timer on pipeline Run button + step elapsed timer in log
- Fixed `_pipelineStartTime` variable declaration

## v25.1.0 — 2026-03-31 00:21
- LLM nav link moved before Workflows in all 12 pages
- Download progress: badge shows `x GB / tot GB (%)` with progress bar
- Auto-starts download poll on page load if download active (interval 2s)
- Added "Downloading" filter toggle in catalog
- Catalog family toggles for Midnight Miqu, Stheno, Darkest Universe
- Launch dropdown sorted alphabetically
- Pipeline requirements: Launch button with dropdown for multi-model selection
- Pipeline image_to_video corrected to use Q8_0 model

## v25.0.0 — 2026-03-30 23:54
- Pipeline engine: `backend/pipelines/` with auto-discovery
- Image to Video pipeline: analyze image → generate multi-scene prompts → parse → submit WAN job
- PipelineContext: llm_chat(), submit_job(), logging, requirement checking
- Background execution with polling status
- Pipelines tab on LLM page with form, requirement checklist, live log viewer

## v24.0.1 — 2026-03-30 21:34
- Instance cards: incremental DOM updates on poll (health dot + VRAM only)
- No more collapsing of open log consoles during polling

## v24.0.0 — 2026-03-30 21:25
- Multimodal chat: image upload, resize to 1024px, storage in `assets/images/llm/`
- Messages store `llm://` references, resolved to base64 at send time with LRU cache
- Multi-file catalog: models with `companions` array (mmproj for VL models)
- Download/delete handles companion files, status shows "partial"
- Launch auto-adds `--mmproj` flag for vision models
- Frontend: image button in chat, multimodal message rendering

## v23.3.2 — 2026-03-30 21:01
- Telegram bot status dots (green/red/gray) in settings card
- Start button enabled from backend `has_token` flag (not DOM)

## v23.3.1 — 2026-03-30 20:57
- Auto-restart loop in `start.sh` for production
- Backend restart simplified to `os._exit(0)` — loop relaunches

## v23.3.0 — 2026-03-30 20:52
- Graceful restart: stops Telegram bot before exit, redirect logs

## v23.2.1 — 2026-03-30 20:48
- Fixed Telegram bot stop (removed non-existent `stop_running()`)
- Styled toggles: notifications in settings and show-private in presets use `.toggle` component

## v23.2.0 — 2026-03-30 20:45
- Telegram notifications toggle in settings card, disabled by default
- Persisted as `TELEGRAM_NOTIFICATIONS` in DB settings

## v23.1.2 — 2026-03-30 20:39
- Model size shown on catalog cards before download (from `expected_bytes`/`size_gb`)
- All 4 DanTagGen variants added to catalog (beta, gamma, delta, delta-rev2)
- Fixed beta `hf_repo` path

## v23.1.1 — 2026-03-30 20:21
- System Prompts dialog: split into left list + right detail panel
- Fixed chatConvArea duplicate `display:none` overriding flex

## v23.1.0 — 2026-03-30 20:14
- Chat presets: removed hardcoded seeds, all managed via DB + UI
- `chat_preset_examples` table for suggested prompts per preset
- Inline editing of name/system prompt/examples in dialog
- Examples shown as clickable suggestions in chat
- LLM catalog: added Uncensored category (Qwen 3.5 27B/35B MoE abliterated), Vision-Language (Qwen3-VL 8B)

## v23.0.0 — 2026-03-30 18:38
- Conversation system with DB persistence (`llm.db`)
- Conversations tied to model (not instance), sticky instance with fallback
- System prompt presets (seeded: Prompt Engineer, General Chat)
- Full CRUD API for presets and conversations
- `/message` endpoint: builds history, proxies to llama-server, persists response
- Token usage tracking with context bar
- LLM page split into Server + Chat tabs
- Chat sidebar with conversation list, new chat dialog, streaming, fullscreen, reset

## v22.5.0 — 2026-03-30 17:37
- Live VRAM per running instance (nvidia-smi per-PID, /proc scan for orphans)
- Chat response timer on Send button + elapsed time under assistant response

## v22.4.0 — 2026-03-30 17:12
- Instance ID format: URL-safe slugs (no colons/dots)
- Proxy route: `/api/admin/llm/proxy/{id}/api/{path}`

## v22.3.2 — 2026-03-30 17:11
- Update button disabled until status loads

## v22.3.1 — 2026-03-30 17:07
- Proxy 520 fix: `Response` instead of `StreamingResponse` (content-length conflict)

## v22.3.0 — 2026-03-30 17:03
- Full DEV_MODE stubs: skip model file check, all catalog models shown as present, proxy stubbed, chat responses variable with streaming delay
- Chat fullscreen overlay toggle
- Launch button aligned with config fields

## v22.2.1 — 2026-03-30 16:54
- Fixed `_now_rome()` datetime serialization (`.strftime()`)
- Verified instance persistence in prod: launch → status → restart → survives

## v22.2.0 — 2026-03-30 16:45
- Instance registry persisted to `llm/instances.json`
- On boot, restored instances port-probed to detect alive orphans
- Orphan stop via `/proc` PID scan + SIGTERM
- Exited instances shown with Dismiss button
- Model catalog collapsed by default

## v22.1.0 — 2026-03-30 16:24
- LLM page telemetry: gauge circles (GPU/VRAM/RAM/CPU/Disk) matching home page
- Model catalog cards: removed running-related state (pure catalog cards)

## v22.0.0 — 2026-03-30 16:14
- LLM multi-instance system with generic proxy
- Accordion model catalog, launch configuration, running instances panel
- Chat panel with instance selector, streaming SSE, temperature slider
- llama-server forced to `--parallel 1`

## v21.2.0 — 2026-03-30 15:54
- Flush DB includes all 3 databases (studio, gallery, telegram)
- Telegram bot: contact tracking DB, /stop unsubscribe, boot notification, command menu

## v21.1.0 — 2026-03-30 15:16
- Home: color-coded Latest column (green match, red mismatch, gray no data)
- DEV_MODE check-for-updates stub, DEV ribbon
- Persistent update prefs with toggle per component
- Toast notification on component toggle change

## v21.0.0 — 2026-03-30 14:22
- Docker: dev setup fixes, container manager scripts, bind-mount safety
- Documentation: rewrite docker README, move RunPod template
- Catalog cleanup: context_max in llm.json
