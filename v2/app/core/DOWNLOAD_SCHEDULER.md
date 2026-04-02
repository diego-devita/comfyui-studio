# Download Scheduler — Architecture

## What it is

An independent background process that executes queued file downloads.
It runs as its own process, separate from the backend and the CLI.

## How it works

1. **Callers** (CLI, backend, gallery) write download requests to the `downloads` table in SQLite
2. **The scheduler process** polls the table, picks up queued items, downloads them, and calls the registered callback to deliver the file to its destination (media store, model store, etc.)
3. **Only one scheduler** runs at a time, enforced by a DB lock with heartbeat

## How to launch it

The scheduler has a single entry point: `v2/app/bin/studio-downloader`

### From shell (direct)
```bash
studio-downloader
# or
python3 v2/app/bin/studio-downloader
```

### From CLI
```bash
studio download start       # spawns studio-downloader as a subprocess
studio download stop        # sends SIGTERM to the running scheduler
studio download running     # checks if it's alive (reads heartbeat)
```

### From backend (at boot)
```python
import subprocess
subprocess.Popen(["python3", "v2/app/bin/studio-downloader"])
```

### From start.sh (as a service)
```bash
python3 "${STUDIO_DIR}/v2/app/bin/studio-downloader" &
```

## Singleton guarantee

Only one scheduler can run at a time across all processes. This is enforced by:

### scheduler_lock table
```sql
CREATE TABLE scheduler_lock (
    id          INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),  -- max one row
    pid         INTEGER NOT NULL,
    started_at  TEXT NOT NULL,
    heartbeat   TEXT NOT NULL
);
```

### Acquisition (init_scheduler)
1. Check `_running` flag — prevents double-start in the same process
2. `BEGIN EXCLUSIVE` — locks the entire DB (no other process can read or write)
3. Read heartbeat — if recent (< 30 seconds), another scheduler is alive → abort
4. Delete stale lock + insert our PID and fresh heartbeat
5. `COMMIT` — releases DB lock
6. Start worker pool + poll thread

### Heartbeat
The poll thread updates the heartbeat every 2 seconds:
```sql
UPDATE scheduler_lock SET heartbeat = ? WHERE id = 1 AND pid = ?
```
If this update returns 0 rows (someone stole our lock), the scheduler stops.

### Timeout
If the heartbeat is older than 30 seconds, the scheduler is considered dead.
The next `init_scheduler()` call will delete the stale lock and take over.

### Graceful stop
`stop_scheduler()` or SIGTERM:
1. Sets `_running = False`
2. Waits for active downloads to finish (`pool.shutdown(wait=True)`)
3. Deletes the lock row

### Ungraceful stop (crash, kill -9)
- Heartbeat stops updating
- After 30 seconds, any new `init_scheduler()` call will take over
- Downloads that were 'downloading' get reset to 'queued' on next startup

## Who enqueues downloads

Anyone can enqueue — it's just an INSERT into the `downloads` table:
```python
from v2.app.core.download import enqueue
enqueue(url="https://...", callback="media_store", callback_args={...})
```

The record sits with `status='queued'` until the scheduler picks it up.
If the scheduler is not running, the record waits indefinitely.

## Callback delivery

When a download completes, the scheduler calls the registered callback:
```python
CALLBACKS["media_store"](downloaded_file_path, callback_args_dict)
```

Callbacks are registered by modules at import time:
```python
from v2.app.core.download import register_callback
register_callback("gallery_deliver", my_function)
```

The callback name is stored in the DB (`downloads.callback`), so it survives
restarts. The function must be re-registered on every startup (happens
automatically when modules are imported).

## CLI commands

```
studio download start      — launch scheduler (if not already running)
studio download stop       — stop scheduler (SIGTERM)
studio download running    — check if scheduler is alive
studio download list       — list download queue
studio download status <id>— detail of a single download
studio download cancel <id>— cancel a download
studio download retry <id> — retry a failed download
studio download cleanup    — remove temp files
studio download queue      — queue statistics
```

## File layout

```
v2/app/
  core/
    download.py             — scheduler logic, enqueue, callbacks
  bin/
    studio-downloader       — standalone entry point
  cli/
    download.py             — CLI commands
```
