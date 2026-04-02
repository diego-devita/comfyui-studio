# Download Scheduler — Architecture

## What it is

An independent background process that executes queued file downloads.
Runs as its own process, separate from the backend and the CLI.

## How it works

```
IDLE                                    WORKING
  │                                       │
  │  inotify sleep (zero CPU, zero DB)    │  drain queue → submit to pool
  │                                       │  workers download files
  │◄──── .wake file appears ──────────────│  callbacks deliver to stores
  │                                       │
  │  timeout 60s (safety) ────────────────│  queue empty → delete .wake
  │                                       │
  └───────────────────────────────────────┘
```

1. **Callers** write download requests to the `downloads` table + touch `.wake`
2. **Scheduler** sleeps on inotify watching the downloads directory
3. **`.wake` appears** → scheduler wakes, processes the entire queue
4. **Queue empty** → deletes `.wake`, goes back to sleep
5. **Safety timeout** → every 60s, wakes anyway in case events were missed

## How to launch

Single entry point: `v2/app/bin/studio-downloader`

```bash
# From shell
studio-downloader

# From CLI
studio download start

# From backend (subprocess)
subprocess.Popen(["python3", "v2/app/bin/studio-downloader"])

# From start.sh (as a service)
python3 "${STUDIO_DIR}/v2/app/bin/studio-downloader" &
```

## Singleton guarantee

Only one scheduler at a time. Enforced by `scheduler_lock` table.

### Lock table
```sql
scheduler_lock (
    id    INTEGER PRIMARY KEY CHECK (id = 1),  -- max one row
    pid   INTEGER NOT NULL,
    started_at TEXT NOT NULL
)
```

### Acquisition (init_scheduler)
1. Same-process check: `_running` flag → prevent double-start
2. `BEGIN EXCLUSIVE` → atomic cross-process lock
3. Read PID from lock → `os.kill(pid, 0)` → alive check
4. If alive → abort. If dead → delete stale + insert our PID
5. `COMMIT`

### Alive check
No heartbeat. PID verified with `os.kill(pid, 0)`:
- Process exists → scheduler is alive
- Process doesn't exist → scheduler is dead, lock is stale

### Graceful stop
1. `_running = False`
2. Touch `.wake` to exit inotify sleep
3. `pool.shutdown(wait=True)` → finish active downloads
4. Delete lock row
5. `PRAGMA wal_checkpoint(TRUNCATE)` → flush WAL
6. Exit

### Crash / kill -9
- PID dies → next `init_scheduler()` sees dead PID → takes over
- Downloads in 'downloading' state → reset to 'queued' on recovery

## Wake mechanism

**Problem:** scheduler should not poll the DB when idle.

**Solution:** filesystem sentinel + inotify.

- `enqueue()` does INSERT + `touch downloads/.wake`
- Scheduler uses Linux `inotify` to watch the directory
- When `.wake` appears → immediate wake (kernel notification, zero polling)
- Fallback: 60s timeout if inotify misses events or isn't available

**When idle:** zero CPU usage, zero DB access. Only the inotify watch (kernel-level, no resources).

## CLI commands

```
studio download start      — spawn scheduler process
studio download stop       — SIGTERM to scheduler PID
studio download running    — check if alive (PID check)
studio download list       — list download queue
studio download status <id>— single download detail
studio download cancel <id>— cancel a download
studio download retry <id> — retry + wake scheduler
studio download cleanup    — remove temp .partial files
studio download queue      — queue statistics
```

## Safety matrix

| Case | What happens |
|------|-------------|
| Two processes launch scheduler | BEGIN EXCLUSIVE → one wins |
| Scheduler crashes | PID dies → next init takes over |
| .wake missed by inotify | 60s timeout → safety wake |
| .wake lost (bug) | 60s timeout → checks queue anyway |
| enqueue without scheduler | Record in DB, waits. .wake file sits there. |
| Stop during download | Pool waits for active downloads → clean exit |
| kill -9 | PID dead → next init reclaims lock |
| Container restart | Same as kill -9 |
| Filesystem full | touch .wake fails (0 bytes) → 60s timeout |
| Clean shutdown | WAL checkpoint → zero pending writes |

## File layout

```
v2/app/
  core/
    download.py              — scheduler logic, queue operations
    DOWNLOAD_SCHEDULER.md    — this file
  bin/
    studio-downloader        — standalone entry point
  cli/
    download.py              — CLI commands
```
