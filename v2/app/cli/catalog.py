"""CLI commands: studio catalog — model catalog operations."""

import json
import sys

from v2.app.cli._common import (
    _init, _bold, _green, _red, _yellow, _cyan, _dim,
    _fmt_bytes, _fmt_date, _table,
)


def _get_catalog():
    _init()
    from v2.app.domain import catalog
    return catalog


def cmd_stats(args):
    cat = _get_catalog()
    s = cat.stats()
    if args.json:
        print(json.dumps(s, indent=2))
        return
    print(f"\n  {_bold('Catalog Statistics')}\n")
    print(f"  Models (parents):  {_cyan(str(s['models']))}")
    print(f"  Versions:          {_cyan(str(s['versions']))}")
    print(f"  Files (catalog):   {_cyan(str(s['files']))}")
    print(f"  Downloaded:        {_green(str(s['downloaded']))}")
    print(f"  Not downloaded:    {_yellow(str(s['not_downloaded']))}")
    print()


def cmd_list(args):
    cat = _get_catalog()
    models = cat.find_models(
        name=args.search, category=args.category, type=args.type,
        limit=args.limit, offset=args.offset,
    )
    if args.json:
        print(json.dumps(models, indent=2, default=str))
        return
    if not models:
        print(_dim("  No models found."))
        return
    print(f"\n  {_bold(f'Models ({len(models)})')}\n")
    _table(
        ["ID", "Name", "Category", "Type", "Creator"],
        [[m["id"][:12] + "...", m["name"][:40], m.get("category") or "-",
          m.get("type") or "-", m.get("creator") or "-"] for m in models],
    )
    print()


def cmd_info(args):
    cat = _get_catalog()
    m = cat.get_model(args.id)
    if not m:
        print(_red(f"  Model not found: {args.id}"))
        sys.exit(1)
    if args.json:
        versions = cat.get_versions_by_model(m["id"])
        m["versions"] = versions
        for v in versions:
            v["files"] = cat.get_version(v["id"]).get("files", [])
        print(json.dumps(m, indent=2, default=str))
        return
    print(f"\n  {_bold('Model Info')}\n")
    print(f"  ID:       {_cyan(m['id'])}")
    print(f"  Name:     {m['name']}")
    print(f"  Category: {m.get('category') or '-'}")
    print(f"  Type:     {m.get('type') or '-'}")
    print(f"  Creator:  {m.get('creator') or '-'}")
    print(f"  NSFW:     {'yes' if m.get('nsfw') else 'no'}")
    if m.get("tags"):
        try:
            print(f"  Tags:     {', '.join(json.loads(m['tags']))}")
        except Exception:
            print(f"  Tags:     {m['tags']}")
    sources = cat.get_sources("model", m["id"])
    for s in sources:
        print(f"  Source:   {s['source']} -> {s['source_id']}" + (f"  {s['source_url']}" if s.get("source_url") else ""))
    versions = cat.get_versions_by_model(m["id"])
    print(f"\n  {_bold(f'Versions ({len(versions)})')}")
    for v in versions:
        vdata = cat.get_version(v["id"])
        files = vdata.get("files", [])
        downloaded = sum(1 for f in files if f.get("store_id"))
        print(f"\n    {_cyan(v['id'][:12])}... {v['name']}")
        print(f"      base_model: {v.get('base_model') or '-'}")
        print(f"      files: {len(files)} ({downloaded} downloaded)")
        for f in files:
            status = _green("DL") if f.get("store_id") else _dim("--")
            role = f.get("role") or ""
            print(f"        {status} {f['file'][:50]} [{f['file_type']}] {role}")
    print()


def cmd_import(args):
    from v2.app.clients.civitai import CivitaiClient
    from v2.app.settings import CIVITAI_API_KEY
    cat = _get_catalog()

    api_key = args.api_key or CIVITAI_API_KEY
    if not api_key:
        print(_red("  CivitAI API key required. Use --api-key or set CIVITAI_API_KEY."))
        sys.exit(1)

    client = CivitaiClient(api_key=api_key)
    print(f"  Fetching model {args.civitai_id} from CivitAI...", end="", flush=True)
    try:
        data = client.get_model(args.civitai_id)
    except Exception as e:
        print(f" {_red(str(e))}")
        sys.exit(1)

    print(f" {_green(data.get('name', '?'))}")
    print(f"  Type: {data.get('type')}  Versions: {len(data.get('modelVersions', []))}")

    version_ids = None
    if args.versions:
        version_ids = [int(v) for v in args.versions.split(",")]
        print(f"  Importing only versions: {version_ids}")

    result = cat.import_from_civitai(civitai_data=data, version_ids=version_ids, category=args.category)

    print(f"\n  {_green('Done:')}")
    print(f"    Model ID:        {result['model_id'][:12]}...")
    print(f"    Versions created: {result['versions_created']}")
    print(f"    Versions skipped: {result['versions_skipped']}")
    print(f"    Files created:    {result['files_created']}")
    print()


def cmd_versions(args):
    cat = _get_catalog()
    versions = cat.get_versions_by_model(args.model_id)
    if args.json:
        print(json.dumps(versions, indent=2, default=str))
        return
    if not versions:
        print(_dim("  No versions found."))
        return
    print(f"\n  {_bold(f'Versions ({len(versions)})')}\n")
    _table(
        ["ID", "Name", "Base Model", "Published"],
        [[v["id"][:12] + "...", v["name"][:35], v.get("base_model") or "-",
          _fmt_date(v.get("published_at") or "")[:10]] for v in versions],
    )
    print()


def cmd_files(args):
    cat = _get_catalog()
    v = cat.get_version(args.version_id)
    if not v:
        print(_red(f"  Version not found: {args.version_id}"))
        sys.exit(1)
    files = v.get("files", [])
    if args.json:
        print(json.dumps(files, indent=2, default=str))
        return
    if not files:
        print(_dim("  No files."))
        return
    vname = v["name"]
    print(f"\n  {_bold(f'Files for {vname} ({len(files)})')}\n")
    for f in files:
        status = _green("DOWNLOADED") if f.get("store_id") else _yellow("NOT DOWNLOADED")
        print(f"  {f['id'][:12]}... {f['file'][:45]}")
        print(f"    type: {f['file_type']}  dest: {f['dest']}  role: {f.get('role') or '-'}  {status}")
    print()


def register(subparsers, common):
    p = subparsers.add_parser("catalog", help="Model catalog operations")
    sub = p.add_subparsers(dest="subcommand", title="subcommands")

    sub.add_parser("stats", help="Catalog statistics", parents=[common]).set_defaults(func=cmd_stats)

    s = sub.add_parser("list", help="List models", parents=[common])
    s.add_argument("--search", "-s"); s.add_argument("--category"); s.add_argument("--type")
    s.add_argument("--limit", type=int, default=50); s.add_argument("--offset", type=int, default=0)
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("info", help="Model detail", parents=[common])
    s.add_argument("id"); s.set_defaults(func=cmd_info)

    s = sub.add_parser("import", help="Import from CivitAI (upsert)", parents=[common])
    s.add_argument("civitai_id", type=int); s.add_argument("--versions"); s.add_argument("--category")
    s.add_argument("--api-key"); s.set_defaults(func=cmd_import)

    s = sub.add_parser("versions", help="List versions", parents=[common])
    s.add_argument("model_id"); s.set_defaults(func=cmd_versions)

    s = sub.add_parser("files", help="List files of a version", parents=[common])
    s.add_argument("version_id"); s.set_defaults(func=cmd_files)
