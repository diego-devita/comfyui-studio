"""CLI commands: studio store — model store operations."""

import json
from v2.app.cli._common import _bold, _dim, _fmt_bytes, _table, _db_conn


def cmd_stats(args):
    from v2.app.stores import model as ms
    if args.json:
        print(json.dumps({"count": ms.count(), "total_bytes": ms.total_size()}, indent=2))
        return
    print(f"\n  {_bold('Model Store')}\n")
    print(f"  Files:      {ms.count()}")
    print(f"  Total size: {_fmt_bytes(ms.total_size())}")
    print()


def cmd_list(args):
    conn = _db_conn()
    rows = conn.execute(
        "SELECT * FROM model_store_files ORDER BY created_at DESC LIMIT ?",
        (args.limit,)
    ).fetchall()
    if args.json:
        print(json.dumps([dict(r) for r in rows], indent=2, default=str))
        return
    if not rows:
        print(_dim("  Model store is empty."))
        return
    print(f"\n  {_bold(f'Model Store Files ({len(rows)})')}\n")
    _table(
        ["ID", "Format", "Precision", "Size", "Original Name"],
        [[r["id"][:12] + "...", r["format"], r.get("precision") or "-",
          _fmt_bytes(r["file_size"]), (r.get("original_name") or "")[:35]] for r in rows],
    )
    print()


def register(subparsers, common):
    p = subparsers.add_parser("store", help="Model store operations",
        description="Physical model file storage.")
    sub = p.add_subparsers(dest="subcommand", title="subcommands")

    s = sub.add_parser("stats", help="Store statistics", parents=[common])
    s.set_defaults(func=cmd_stats)

    s = sub.add_parser("list", help="List stored files", parents=[common])
    s.add_argument("--limit", type=int, default=50)
    s.set_defaults(func=cmd_list)
