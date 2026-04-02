"""CLI commands: studio db — database operations."""

import json
from v2.app.cli._common import _bold, _green, _red, _fmt_bytes


def cmd_tables(args):
    """Handle `studio db tables` command."""
    from v2.app.core.db import table_list, table_count
    tables = table_list()
    if args.json:
        print(json.dumps({t: table_count(t) for t in tables}, indent=2))
        return
    print(f"\n  {_bold(f'Tables ({len(tables)})')}\n")
    for t in tables:
        count = table_count(t)
        print(f"  {t:30s} {count:>8d} rows")
    print()


def cmd_integrity(args):
    """Handle `studio db integrity` command."""
    from v2.app.core.db import integrity_check
    result = integrity_check()
    if result == "ok":
        print(f"  {_green('Database integrity OK')}")
    else:
        print(f"  {_red(f'Integrity issue: {result}')}")


def cmd_size(args):
    """Handle `studio db size` command."""
    from v2.app.core.db import db_size_bytes
    size = db_size_bytes()
    if args.json:
        print(json.dumps({"bytes": size}))
        return
    print(f"  Database size: {_fmt_bytes(size)}")


def register(subparsers, common):
    """Register db subcommands with the argument parser."""
    p = subparsers.add_parser("db", help="Database operations",
        description="Database inspection and maintenance.")
    sub = p.add_subparsers(dest="subcommand", title="subcommands")

    s = sub.add_parser("tables", help="List tables with row counts", parents=[common])
    s.set_defaults(func=cmd_tables)

    s = sub.add_parser("integrity", help="Run integrity check", parents=[common])
    s.set_defaults(func=cmd_integrity)

    s = sub.add_parser("size", help="Database file size", parents=[common])
    s.set_defaults(func=cmd_size)
