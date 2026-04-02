"""CLI commands: studio http — HTTP client stats and log."""

import json
from v2.app.cli._common import _bold, _green, _red, _dim, _fmt_bytes


def cmd_stats(args):
    """Handle `studio http stats` command."""
    from v2.app.core.http_client import http
    s = http.get_stats()
    if args.json:
        print(json.dumps({
            "total_calls": s.total_calls, "total_errors": s.total_errors,
            "total_bytes": s.total_bytes, "avg_duration_ms": round(s.avg_duration_ms, 1),
            "calls_by_caller": s.calls_by_caller, "errors_by_caller": s.errors_by_caller,
        }, indent=2))
        return
    print(f"\n  {_bold('HTTP Client Statistics')}\n")
    print(f"  Total calls:    {s.total_calls}")
    print(f"  Total errors:   {s.total_errors}")
    print(f"  Total bytes:    {_fmt_bytes(s.total_bytes)}")
    print(f"  Avg duration:   {s.avg_duration_ms:.0f} ms")
    if s.calls_by_caller:
        print(f"\n  {_bold('By caller:')}")
        for caller, count in sorted(s.calls_by_caller.items()):
            errors = s.errors_by_caller.get(caller, 0)
            err_str = f" ({_red(f'{errors} errors')})" if errors else ""
            print(f"    {caller:40s} {count:>5d}{err_str}")
    print()


def cmd_log(args):
    """Handle `studio http log` command."""
    from v2.app.core.http_client import http
    entries = http.get_log(limit=args.limit, caller=args.caller)
    if args.json:
        print(json.dumps([{
            "timestamp": e.timestamp, "method": e.method, "url": e.url,
            "status": e.status, "duration_ms": e.duration_ms,
            "caller": e.caller, "error": e.error, "bytes": e.response_bytes,
        } for e in entries], indent=2))
        return
    if not entries:
        print(_dim("  No HTTP calls logged."))
        return
    print(f"\n  {_bold(f'HTTP Log (last {len(entries)})')}\n")
    for e in entries:
        status_str = _green(str(e.status)) if e.status < 400 else _red(str(e.status))
        print(f"  {status_str} {e.duration_ms:>5d}ms {e.method} {e.url[:70]}")
        if e.caller:
            print(f"    {_dim(e.caller)}")
        if e.error:
            print(f"    {_red(e.error[:100])}")
    print()


def register(subparsers, common):
    """Register http subcommands with the argument parser."""
    p = subparsers.add_parser("http", help="HTTP client stats and log",
        description="Monitor outgoing HTTP API calls.")
    sub = p.add_subparsers(dest="subcommand", title="subcommands")

    s = sub.add_parser("stats", help="HTTP call statistics", parents=[common])
    s.set_defaults(func=cmd_stats)

    s = sub.add_parser("log", help="Recent HTTP calls", parents=[common])
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--caller", help="Filter by caller name")
    s.set_defaults(func=cmd_log)
