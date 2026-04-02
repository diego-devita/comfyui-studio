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


def register(subparsers, common):
    """Register download subcommands with the argument parser."""
    p = subparsers.add_parser("download", help="Download queue operations")
    sub = p.add_subparsers(dest="subcommand", title="subcommands")

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
