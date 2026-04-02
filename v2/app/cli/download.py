"""CLI commands: studio download — download queue operations."""

import json
import sys

from v2.app.cli._common import (
    _init, _bold, _green, _red, _cyan, _dim,
    _fmt_bytes, _fmt_date, _table,
)


def _get_scheduler():
    """Lazy import of domain module."""
    _init()
    from v2.app.core import download
    return download


def cmd_list(args):
    """Handle `studio download list` command."""
    dl = _get_scheduler()
    rows = dl.list_active() if args.active else dl.list_all(limit=args.limit)
    if args.json:
        print(json.dumps(rows, indent=2, default=str))
        return
    if not rows:
        print(_dim("  No downloads."))
        return
    print(f"\n  {_bold(f'Downloads ({len(rows)})')}\n")
    _table(
        ["ID", "Status", "Progress", "Callback", "Created"],
        [[r["id"][:12] + "...", r["status"],
          f"{r.get('downloaded_bytes', 0) or 0}/{r.get('total_bytes') or '?'}",
          r["callback"], _fmt_date(r["created_at"])[:16]] for r in rows],
    )
    print()


def cmd_status(args):
    """Handle `studio download status` command."""
    dl = _get_scheduler()
    r = dl.get_status(args.id)
    if not r:
        print(_red(f"  Download not found: {args.id}"))
        sys.exit(1)
    if args.json:
        print(json.dumps(r, indent=2, default=str))
        return
    print(f"\n  {_bold('Download')}\n")
    print(f"  ID:         {_cyan(r['id'])}")
    print(f"  URL:        {r['url'][:80]}")
    print(f"  Status:     {r['status']}")
    print(f"  Progress:   {_fmt_bytes(r.get('downloaded_bytes', 0) or 0)} / {_fmt_bytes(r.get('total_bytes') or 0)}")
    print(f"  Callback:   {r['callback']}")
    print(f"  Retries:    {r.get('retries', 0)}/{r.get('max_retries', 3)}")
    if r.get("error"):
        print(f"  Error:      {_red(r['error'][:200])}")
    print(f"  Created:    {_fmt_date(r['created_at'])}")
    if r.get("started_at"):
        print(f"  Started:    {_fmt_date(r['started_at'])}")
    if r.get("completed_at"):
        print(f"  Completed:  {_fmt_date(r['completed_at'])}")
    print()


def cmd_cancel(args):
    """Handle `studio download cancel` command."""
    dl = _get_scheduler()
    if dl.cancel(args.id):
        print(f"  {_green('Cancelled')} {args.id}")
    else:
        print(_red(f"  Not found or already terminal: {args.id}"))


def cmd_retry(args):
    """Handle `studio download retry` command."""
    dl = _get_scheduler()
    if dl.retry(args.id):
        print(f"  {_green('Requeued')} {args.id}")
    else:
        print(_red(f"  Not found or not in retryable state: {args.id}"))


def cmd_cleanup(args):
    """Handle `studio download cleanup` command."""
    dl = _get_scheduler()
    removed = dl.cleanup_temp()
    print(f"  {_green(f'{removed} temp file(s) removed')}")


def cmd_queue(args):
    """Handle `studio download queue` command."""
    dl = _get_scheduler()
    q = dl.queue_size()
    if args.json:
        print(json.dumps(q, indent=2))
        return
    print(f"\n  {_bold('Download Queue')}\n")
    for status, count in q.items():
        print(f"  {status:15s} {count}")
    print()


def cmd_start(args):
    """Launch the download scheduler as a subprocess."""
    dl = _get_scheduler()
    if dl.is_running():
        from v2.app.cli._common import _green
        print(f"  {_green('Scheduler is already running.')}")
        return
    import subprocess, os
    from v2.app.core.settings import STUDIO_DIR
    launcher = STUDIO_DIR / "v2" / "app" / "bin" / "studio-downloader"
    if not launcher.exists():
        print(_red(f"  Launcher not found: {launcher}"))
        sys.exit(1)
    env = os.environ.copy()
    proc = subprocess.Popen(
        [sys.executable, str(launcher)],
        env=env,
        stdout=None if args.verbose else subprocess.DEVNULL,
        stderr=None if args.verbose else subprocess.DEVNULL,
    )
    import time
    time.sleep(1)
    if dl.is_running():
        from v2.app.cli._common import _green
        print(f"  {_green(f'Scheduler started (PID {proc.pid})')}")
    else:
        print(_red(f"  Scheduler failed to start. Run with --verbose to see output."))


def cmd_stop(args):
    """Signal the running scheduler to stop."""
    dl = _get_scheduler()
    if not dl.is_running():
        print(_dim("  Scheduler is not running."))
        return
    from v2.app.core.db import get_conn
    conn = get_conn()
    row = conn.execute("SELECT pid FROM scheduler_lock WHERE id = 1").fetchone()
    if not row:
        print(_dim("  No scheduler lock found."))
        return
    pid = row["pid"]
    import os, signal
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"  {_green(f'Sent SIGTERM to PID {pid}')}")
    except ProcessLookupError:
        # PID doesn't exist — clean up stale lock
        conn.execute("DELETE FROM scheduler_lock WHERE id = 1")
        conn.commit()
        print(f"  {_yellow(f'PID {pid} not found. Cleaned stale lock.')}")
    except PermissionError:
        print(_red(f"  Permission denied to signal PID {pid}."))


def cmd_running(args):
    """Check if the download scheduler is running."""
    dl = _get_scheduler()
    running = dl.is_running()
    if args.json:
        print(json.dumps({"running": running}))
        return
    if running:
        from v2.app.core.db import get_conn
        conn = get_conn()
        row = conn.execute("SELECT pid, started_at, heartbeat FROM scheduler_lock WHERE id = 1").fetchone()
        print(f"  {_green('Scheduler is running')}")
        if row:
            print(f"  PID:       {row['pid']}")
            print(f"  Started:   {_fmt_date(row['started_at'])}")
            print(f"  Heartbeat: {_fmt_date(row['heartbeat'])}")
    else:
        print(f"  {_dim('Scheduler is not running.')}")


def register(subparsers, common):
    """Register download subcommands with the argument parser."""
    p = subparsers.add_parser("download", help="Download queue and scheduler operations")
    sub = p.add_subparsers(dest="subcommand", title="subcommands")

    sub.add_parser("start", help="Launch the download scheduler", parents=[common]).set_defaults(func=cmd_start)
    sub.add_parser("stop", help="Stop the download scheduler", parents=[common]).set_defaults(func=cmd_stop)
    sub.add_parser("running", help="Check if scheduler is running", parents=[common]).set_defaults(func=cmd_running)

    s = sub.add_parser("list", help="List downloads", parents=[common])
    s.add_argument("--active", action="store_true"); s.add_argument("--limit", type=int, default=50)
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("status", help="Download detail", parents=[common])
    s.add_argument("id"); s.set_defaults(func=cmd_status)

    s = sub.add_parser("cancel", help="Cancel", parents=[common])
    s.add_argument("id"); s.set_defaults(func=cmd_cancel)

    s = sub.add_parser("retry", help="Retry", parents=[common])
    s.add_argument("id"); s.set_defaults(func=cmd_retry)

    sub.add_parser("cleanup", help="Remove temp files", parents=[common]).set_defaults(func=cmd_cleanup)
    sub.add_parser("queue", help="Queue stats", parents=[common]).set_defaults(func=cmd_queue)
