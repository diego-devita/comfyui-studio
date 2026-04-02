"""CLI commands: studio media — media store operations."""

import argparse
import json
import sys
from pathlib import Path
from textwrap import dedent

from v2.app.cli._common import (
    _init, _bold, _green, _red, _yellow, _cyan, _dim,
    _fmt_bytes, _fmt_date, _table,
)


def _ms():
    _init()
    from v2.app.stores import media
    return media


def cmd_stats(args):
    ms = _ms()
    s = ms.stats()
    if args.json:
        s["total_on_disk"] = s["total_bytes"] + s["total_thumb_bytes"]
        print(json.dumps(s, indent=2))
        return
    total_on_disk = s["total_bytes"] + s["total_thumb_bytes"]
    print(f"\n  {_bold('Media Store Statistics')}\n")
    print(f"  Total files:     {_cyan(str(s['total_count']))}")
    print(f"  Originals:       {_fmt_bytes(s['total_bytes'])}")
    print(f"  Thumbnails:      {_fmt_bytes(s['total_thumb_bytes'])}")
    print(f"  Total on disk:   {_bold(_fmt_bytes(total_on_disk))}")
    print(f"  Thumb coverage:  {s['thumb_coverage']}/{s['total_count']} files")
    if s["by_type"]:
        print(f"\n  {_bold('By type:')}")
        for k, v in s["by_type"].items():
            print(f"    {k:10s}  {v['count']:>6d} files  {_fmt_bytes(v['bytes']):>10s}")
    if s["by_origin"]:
        print(f"\n  {_bold('By origin:')}")
        for k, v in s["by_origin"].items():
            print(f"    {k:12s}  {v['count']:>6d} files  {_fmt_bytes(v['bytes']):>10s}")
    if s["by_format"]:
        print(f"\n  {_bold('By format:')}")
        for k, v in s["by_format"].items():
            print(f"    {k:12s}  {v['count']:>6d} files  {_fmt_bytes(v['bytes']):>10s}")
    if s["thumbs"]:
        print(f"\n  {_bold('Thumbnails:')}")
        for k, v in s["thumbs"].items():
            print(f"    {k:4s}  {v['count']:>6d} thumbs  {_fmt_bytes(v['bytes']):>10s}")
    if s["by_schema"]:
        print(f"\n  {_bold('Schema versions:')}")
        current = _ms().SCHEMA_VERSION
        for ver, cnt in s["by_schema"].items():
            marker = _green("(current)") if ver == current else _yellow("(outdated)")
            print(f"    v{ver}  {cnt:>6d} files  {marker}")
    print()


def cmd_list(args):
    ms = _ms()
    rows, total = ms.find(
        type=args.type, origin=args.origin, ext=args.format,
        search=args.search, sort=args.sort, desc=args.desc,
        limit=args.limit, offset=args.offset,
    )
    if args.json:
        print(json.dumps({"total": total, "showing": len(rows), "offset": args.offset, "items": rows}, indent=2, default=str))
        return
    if not rows:
        print(_dim("  No media found."))
        return
    print(f"\n  {_bold(f'Media files')} ({len(rows)} of {total})\n")
    _table(
        ["ID", "Type", "Ext", "Name", "Size", "Origin", "Dimensions", "Created"],
        [[r["id"][:12] + "...", r["type"], r["ext"], (r["original_name"] or "")[:30],
          _fmt_bytes(r["file_size"]), r["origin"],
          f"{r['width']}x{r['height']}" if r.get("width") else "-",
          _fmt_date(r["created_at"])[:19]] for r in rows],
    )
    if total > args.offset + args.limit:
        print(_dim(f"\n  ... {total - args.offset - args.limit} more. Use --offset {args.offset + args.limit}"))
    print()


def cmd_info(args):
    ms = _ms()
    m = ms.get_by_prefix(args.id)
    if not m:
        print(_red(f"  Media not found: {args.id}")); sys.exit(1)
    if args.json:
        if m.get("exif"):
            try: m["exif"] = json.loads(m["exif"])
            except: pass
        print(json.dumps(m, indent=2, default=str)); return
    thumbs = ms.get_thumbs(m["id"])
    file_exists = ms._abs_path(m["file_path"]).exists()
    print(f"\n  {_bold('Media Info')}\n")
    print(f"  ID:            {_cyan(m['id'])}")
    print(f"  File:          {m['file_path']}")
    print(f"  On disk:       {_green('YES') if file_exists else _red('MISSING')}")
    print(f"  Original name: {m.get('original_name') or '-'}")
    print(f"  Type:          {m['type']}")
    print(f"  Extension:     {m['ext']}")
    print(f"  MIME:          {m.get('mime') or '-'}")
    print(f"  Size:          {_fmt_bytes(m['file_size'])}")
    print(f"  Dimensions:    {m.get('width', '-')}x{m.get('height', '-')}")
    if m["type"] == "video":
        print(f"  Duration:      {m.get('duration') or '-'}s")
        print(f"  FPS:           {m.get('fps') or '-'}")
        print(f"  Audio:         {'yes' if m.get('audio') else 'no'}")
    print(f"  Codec:         {m.get('codec') or '-'}")
    print(f"  Color space:   {m.get('color_space') or '-'}")
    print(f"  Bit depth:     {m.get('bit_depth') or '-'}")
    print(f"  Alpha:         {'yes' if m.get('has_alpha') else 'no'}")
    print(f"  Hash:          {m.get('hash') or '-'}")
    print(f"  Schema:        v{m.get('schema_version', '?')}")
    print(f"  Origin:        {m['origin']}" + (f" (id: {m.get('origin_id')})" if m.get("origin_id") else ""))
    if m.get("origin_url"): print(f"  Origin URL:    {m['origin_url']}")
    print(f"  Created:       {_fmt_date(m.get('created_at', ''))}")
    if thumbs:
        print(f"\n  {_bold('Thumbnails:')}")
        for t in thumbs:
            t_exists = ms._abs_path(t["file_path"]).exists()
            print(f"    {_green('✓') if t_exists else _red('✗')} {t['size']:4s}  {t['width']}x{t['height']}  {_fmt_bytes(t['file_size'])}")
    if m.get("exif"):
        print(f"\n  {_bold('EXIF / Embedded metadata:')}")
        try:
            exif = json.loads(m["exif"])
            for k, v in exif.items():
                vs = str(v)[:80]
                print(f"    {k}: {vs}")
        except: print(f"    {_dim('(unparseable)')}")
    print()


def cmd_find(args):
    ms = _ms()
    if args.hash:
        results = [ms.get_by_hash(args.hash)] if ms.get_by_hash(args.hash) else []
    elif args.origin and args.origin_id:
        r = ms.get_by_origin(args.origin, args.origin_id)
        results = [r] if r else []
    elif args.name:
        results = ms.find_by_name(args.name)
    else:
        print(_red("  Provide --hash, --origin+--origin-id, or --name")); sys.exit(1)
    if args.json:
        print(json.dumps(results, indent=2, default=str)); return
    if not results:
        print(_dim("  No matches.")); return
    print(f"\n  {_bold(f'Found {len(results)} match(es)')}\n")
    for r in results:
        print(f"  {_cyan(r['id'])}")
        print(f"    {r['type']} {r['ext']}  {_fmt_bytes(r['file_size'])}  origin={r['origin']}")
        if r.get("original_name"): print(f"    name: {r['original_name']}")
    print()


def cmd_doctor(args):
    ms = _ms()
    issues, fixed = [], 0
    print(f"\n  {_bold('Media Store Doctor')}\n")

    # 1. Missing files
    print("  Checking files on disk...", end="", flush=True)
    from v2.app.db import get_conn
    conn = get_conn()
    all_media = conn.execute("SELECT id, file_path FROM media").fetchall()
    missing = [r for r in all_media if not ms._abs_path(r["file_path"]).exists()]
    if missing:
        print(f" {_red(f'{len(missing)} missing')}")
        for r in missing:
            issues.append(("missing_file", r["id"], r["file_path"]))
            if args.verbose: print(f"    {_red('✗')} {r['id'][:12]}... → {r['file_path']}")
        if args.fix:
            for _, mid, _ in [i for i in issues if i[0] == "missing_file"]:
                conn.execute("DELETE FROM media WHERE id = ?", (mid,)); fixed += 1
            conn.commit(); print(f"    {_green(f'Fixed: removed {len(missing)} orphan records')}")
    else:
        print(f" {_green('all OK')}")

    # 2. Orphan files
    print("  Scanning for orphan files...", end="", flush=True)
    media_paths, thumb_paths = ms.all_file_paths()
    all_known = media_paths | thumb_paths
    orphans = []
    if ms.MEDIA_STORE_DIR.exists():
        for f in ms.MEDIA_STORE_DIR.rglob("*"):
            if f.is_file():
                rel = str(f.relative_to(ms.MEDIA_STORE_DIR))
                if rel not in all_known:
                    orphans.append((rel, f.stat().st_size))
    if orphans:
        total_waste = sum(s for _, s in orphans)
        print(f" {_yellow(f'{len(orphans)} orphans ({_fmt_bytes(total_waste)})')}")
        for rel, size in orphans:
            issues.append(("orphan_file", rel, size))
        if args.fix:
            for _, rel, _ in [i for i in issues if i[0] == "orphan_file"]:
                (ms.MEDIA_STORE_DIR / rel).unlink(missing_ok=True); fixed += 1
            print(f"    {_green(f'Fixed: removed {len(orphans)} orphan files')}")
    else:
        print(f" {_green('none')}")

    # 3. Missing thumbs
    print("  Checking thumbnails...", end="", flush=True)
    thumb_rows = conn.execute("SELECT media_id, file_path FROM media_thumbs").fetchall()
    bad_thumbs = [r for r in thumb_rows if not ms._abs_path(r["file_path"]).exists()]
    if bad_thumbs:
        print(f" {_yellow(f'{len(bad_thumbs)} missing')}")
        for r in bad_thumbs: issues.append(("missing_thumb", r["media_id"], r["file_path"]))
        if args.fix:
            for r in bad_thumbs:
                conn.execute("DELETE FROM media_thumbs WHERE media_id = ? AND file_path = ?", (r["media_id"], r["file_path"]))
            conn.commit(); fixed += len(bad_thumbs)
            print(f"    {_green(f'Fixed: removed {len(bad_thumbs)} broken thumb records')}")
    else:
        print(f" {_green('all OK')}")

    # 4. Schema versions
    print("  Checking schema versions...", end="", flush=True)
    outdated = ms.outdated_schema_count(ms.SCHEMA_VERSION)
    if outdated:
        print(f" {_yellow(f'{outdated} outdated (current: v{ms.SCHEMA_VERSION})')}")
        issues.append(("outdated_schema", outdated, ms.SCHEMA_VERSION))
    else:
        print(f" {_green('all current')}")

    # 5. Optional hash verification
    if args.verify_hashes:
        print("  Verifying file hashes...", end="", flush=True)
        rows = conn.execute("SELECT id, file_path, hash FROM media WHERE hash IS NOT NULL").fetchall()
        mismatches = []
        for i, r in enumerate(rows):
            p = ms._abs_path(r["file_path"])
            if p.exists() and ms.compute_hash(p) != r["hash"]:
                mismatches.append(r["id"])
            if (i+1) % 100 == 0: print(f"\r  Verifying file hashes... {i+1}/{len(rows)}", end="", flush=True)
        if mismatches:
            print(f"\r  Verifying file hashes... {_red(f'{len(mismatches)} CORRUPTED')}")
        else:
            print(f"\r  Verifying file hashes... {_green(f'all OK ({len(rows)} verified)')}")

    print(f"\n  {'─' * 40}")
    if issues:
        print(f"  {_bold(f'{len(issues)} issue(s)')}" + (f" ({_green(f'{fixed} fixed')})" if args.fix else f"  Run with {_cyan('--fix')}"))
    else:
        print(f"  {_green('No issues. Media store is healthy.')}")
    print()


def cmd_reindex(args):
    ms = _ms()
    rows = ms.find_for_reindex(force=args.force)
    if not rows:
        print(_green("  Everything up to date.")); return
    print(f"\n  Reindexing {len(rows)} files...\n")
    import time; start = time.time()
    processed, errors = 0, 0
    for i, r in enumerate(rows):
        fp = ms._abs_path(r["file_path"])
        if not fp.exists(): errors += 1; continue
        try:
            updates = {}
            if not args.exif_only and not args.thumbs_only:
                props = ms.extract_properties(fp, r["type"])
                updates.update(props)
                updates["file_size"] = fp.stat().st_size
            if not args.thumbs_only and not args.properties_only:
                exif = ms.extract_exif(fp, r["type"])
                updates["exif"] = json.dumps(exif) if exif else None
            if not args.exif_only and not args.properties_only:
                ms.delete_thumbs(r["id"])
                thumbs = ms.generate_thumbs(r["id"], fp, r["type"])
                ms.insert_thumbs(r["id"], thumbs)
            updates["schema_version"] = ms.SCHEMA_VERSION
            ms.update_fields(r["id"], **updates)
            processed += 1
        except Exception as e:
            errors += 1
            if args.verbose: print(f"    {_red('✗')} {r['id'][:12]}: {e}")
        if (i+1) % 10 == 0 or i+1 == len(rows):
            elapsed = time.time() - start
            rate = (i+1) / elapsed if elapsed > 0 else 0
            eta = int((len(rows)-i-1) / rate) if rate > 0 else 0
            print(f"\r  [{i+1}/{len(rows)}] {rate:.1f}/s  ~{eta}s left  ", end="", flush=True)
    print(f"\r  {_green(f'Done: {processed} processed, {errors} errors in {time.time()-start:.1f}s')}          \n")


def cmd_import(args):
    ms = _ms()
    source = Path(args.path)
    if not source.exists():
        print(_red(f"  Path not found: {source}")); sys.exit(1)
    files = [source] if source.is_file() else (sorted(source.rglob("*")) if args.recursive else [])
    files = [f for f in files if f.is_file() and f.suffix.lower() in ms.ALLOWED]
    if not files:
        print(_dim("  No importable files.")); return
    print(f"\n  Importing {len(files)} file(s)...\n")
    imported, skipped, errors = 0, 0, 0
    for f in files:
        try:
            import shutil, tempfile
            tmp = Path(tempfile.mkdtemp()) / f.name; shutil.copy2(f, tmp)
            ms.store(tmp, origin=args.origin or "upload", origin_id=args.origin_id, original_name=f.name)
            print(f"  {_green('✓')} {f.name}"); imported += 1
        except Exception as e:
            if ms.hash_exists(ms.compute_hash(f)):
                print(f"  {_dim('=')} {f.name} (duplicate)"); skipped += 1
            else:
                print(f"  {_red('✗')} {f.name}: {e}"); errors += 1
    print(f"\n  {imported} imported, {skipped} skipped, {errors} errors\n")


def cmd_export(args):
    ms = _ms()
    path = ms.serve_path(args.id)
    if not path: print(_red(f"  Not found: {args.id}")); sys.exit(1)
    import shutil; dest = Path(args.dest)
    if dest.is_dir():
        m = ms.get(args.id); dest = dest / (m.get("original_name") or path.name)
    shutil.copy2(path, dest); print(f"  {_green('✓')} Exported to {dest}")
    if args.with_thumbs:
        for t in ms.get_thumbs(args.id):
            tp = ms._abs_path(t["file_path"])
            if tp.exists():
                shutil.copy2(tp, dest.parent / f"{dest.stem}.thumb.{t['size']}{dest.suffix}")
    print()


def cmd_delete(args):
    ms = _ms()
    resolved = []
    for mid in args.ids:
        m = ms.get_by_prefix(mid)
        if m: resolved.append(m)
        else: print(f"  {_yellow('?')} {mid} — not found")
    if not resolved: return
    if not args.force:
        print(f"\n  About to delete {len(resolved)} media:\n")
        for r in resolved:
            print(f"    {r['id'][:12]}... {r.get('original_name', '')} ({_fmt_bytes(r['file_size'])})")
        if input("\n  Continue? [y/N] ").strip().lower() != "y": print("  Cancelled."); return
    for r in resolved:
        if ms.delete(r["id"]): print(f"  {_green('✓')} Deleted {r['id'][:12]}...")
        else: print(f"  {_red('✗')} Failed {r['id'][:12]}...")
    print()


def cmd_verify(args):
    ms = _ms()
    from v2.app.db import get_conn; conn = get_conn()
    if args.id:
        rows = conn.execute("SELECT id, file_path, hash FROM media WHERE id LIKE ?", (args.id + "%",)).fetchall()
    elif args.all:
        rows = conn.execute("SELECT id, file_path, hash FROM media WHERE hash IS NOT NULL").fetchall()
    else: print(_red("  Provide --id or --all")); sys.exit(1)
    if not rows: print(_dim("  No files.")); return
    import time; start = time.time()
    ok, bad, missing = 0, 0, 0
    for r in rows:
        p = ms._abs_path(r["file_path"])
        if not p.exists(): missing += 1; continue
        if ms.compute_hash(p) == r["hash"]: ok += 1
        else:
            print(f"  {_red('✗')} {r['id'][:12]}... HASH MISMATCH"); bad += 1
    print(f"\n  {_green(f'{ok} OK')}, {_red(f'{bad} corrupted') if bad else '0 corrupted'}, {missing} missing ({time.time()-start:.1f}s)\n")


def cmd_dedup(args):
    ms = _ms()
    dupes = ms.find_duplicates()
    if not dupes: print(_green("  No duplicates.")); return
    if args.json: print(json.dumps([dict(d) for d in dupes], indent=2)); return
    total_waste = 0
    print(f"\n  {_bold(f'{len(dupes)} duplicate group(s)')}\n")
    from v2.app.db import get_conn; conn = get_conn()
    for d in dupes:
        ids = d["ids"].split(",")
        rows = conn.execute(
            f"SELECT id, original_name, file_size, origin FROM media WHERE id IN ({','.join('?' * len(ids))})", ids
        ).fetchall()
        print(f"  Hash: {d['hash'][:24]}... ({d['cnt']} copies)")
        for r in rows:
            print(f"    {r['id'][:12]}... {r['original_name'] or '-':30s} {_fmt_bytes(r['file_size']):>10s}  {r['origin']}")
        waste = rows[0]["file_size"] * (len(rows) - 1); total_waste += waste
        print(f"    {_dim(f'Wasted: {_fmt_bytes(waste)}')}\n")
    print(f"  Total wasted: {_yellow(_fmt_bytes(total_waste))}\n")


def cmd_exif(args):
    ms = _ms()
    m = ms.get_by_prefix(args.id)
    if not m: print(_red(f"  Not found: {args.id}")); sys.exit(1)
    if not m.get("exif"): print(_dim(f"  No metadata for {m['id'][:12]}...")); return
    exif = json.loads(m["exif"])
    if args.raw or args.json: print(json.dumps(exif, indent=2, default=str)); return
    print(f"\n  {_bold('Embedded metadata')} for {m['id'][:12]}...\n")
    print(f"  Source: {_cyan(exif.get('_source', 'unknown'))}\n")
    for k, v in exif.items():
        if k.startswith("_"): continue
        print(f"  {_dim(k + ':'):30s} {str(v)[:100]}")
    print()


def cmd_thumb(args):
    ms = _ms()
    m = ms.get_by_prefix(args.id)
    if not m: print(_red(f"  Not found: {args.id}")); sys.exit(1)
    fp = ms._abs_path(m["file_path"])
    if not args.regenerate:
        thumbs = ms.get_thumbs(m["id"])
        if not thumbs: print(_dim(f"  No thumbnails.")); return
        print(f"\n  {_bold('Thumbnails')} for {m['id'][:12]}...\n")
        for t in thumbs:
            exists = ms._abs_path(t["file_path"]).exists()
            print(f"  {_green('✓') if exists else _red('✗')}  {t['size']:4s}  {t['width']}x{t['height']}  {_fmt_bytes(t['file_size'])}")
        print(); return
    if not fp.exists(): print(_red(f"  Original missing.")); sys.exit(1)
    ms.delete_thumbs(m["id"])
    if args.size:
        max_side = ms.THUMB_SIZES.get(args.size)
        if not max_side: print(_red(f"  Unknown size: {args.size}")); sys.exit(1)
        rel = f"{ms._shard_dir(m['id'])}/{m['id']}.thumb.{args.size}.jpg"
        dest = ms._abs_path(rel)
        ok = (ms._generate_image_thumb(fp, dest, max_side) if m["type"] == "image"
              else ms._generate_video_thumb(fp, dest, max_side))
        thumbs = []
        if ok:
            from PIL import Image; img = Image.open(dest)
            thumbs = [{"size": args.size, "file_path": rel, "file_size": dest.stat().st_size,
                        "width": img.width, "height": img.height}]; img.close()
    else:
        thumbs = ms.generate_thumbs(m["id"], fp, m["type"])
    ms.insert_thumbs(m["id"], thumbs)
    print(f"  {_green(f'Generated {len(thumbs)} thumbnail(s)')}")
    for t in thumbs: print(f"    {t['size']:4s}  {t['width']}x{t['height']}  {_fmt_bytes(t['file_size'])}")
    print()


def register(subparsers, common):
    p = subparsers.add_parser("media", help="Media store operations",
        description="Manage the centralised media file store.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="subcommand", title="subcommands")

    sub.add_parser("stats", help="Show store statistics", parents=[common]).set_defaults(func=cmd_stats)

    s = sub.add_parser("list", help="List media files", parents=[common])
    s.add_argument("--type", choices=["image", "video"]); s.add_argument("--origin")
    s.add_argument("--format"); s.add_argument("--search", "-s")
    s.add_argument("--sort", default="created_at"); s.add_argument("--desc", action="store_true")
    s.add_argument("--limit", type=int, default=50); s.add_argument("--offset", type=int, default=0)
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("info", help="Media detail", parents=[common])
    s.add_argument("id"); s.set_defaults(func=cmd_info)

    s = sub.add_parser("find", help="Search media", parents=[common])
    s.add_argument("--hash"); s.add_argument("--origin"); s.add_argument("--origin-id"); s.add_argument("--name")
    s.set_defaults(func=cmd_find)

    s = sub.add_parser("doctor", help="Check consistency", parents=[common])
    s.add_argument("--fix", action="store_true"); s.add_argument("--verify-hashes", action="store_true")
    s.set_defaults(func=cmd_doctor)

    s = sub.add_parser("reindex", help="Reprocess metadata/thumbs", parents=[common])
    s.add_argument("--force", action="store_true"); s.add_argument("--thumbs-only", action="store_true")
    s.add_argument("--exif-only", action="store_true"); s.add_argument("--properties-only", action="store_true")
    s.set_defaults(func=cmd_reindex)

    s = sub.add_parser("import", help="Import files", parents=[common])
    s.add_argument("path"); s.add_argument("--origin", default="upload"); s.add_argument("--origin-id")
    s.add_argument("--recursive", "-r", action="store_true"); s.set_defaults(func=cmd_import)

    s = sub.add_parser("export", help="Export file", parents=[common])
    s.add_argument("id"); s.add_argument("dest"); s.add_argument("--with-thumbs", action="store_true")
    s.set_defaults(func=cmd_export)

    s = sub.add_parser("delete", help="Delete media", parents=[common])
    s.add_argument("ids", nargs="+"); s.add_argument("--force", "-f", action="store_true")
    s.set_defaults(func=cmd_delete)

    s = sub.add_parser("verify", help="Verify hashes", parents=[common])
    s.add_argument("--id"); s.add_argument("--all", action="store_true")
    s.set_defaults(func=cmd_verify)

    s = sub.add_parser("dedup", help="Find duplicates", parents=[common])
    s.add_argument("--dry-run", action="store_true"); s.set_defaults(func=cmd_dedup)

    s = sub.add_parser("exif", help="Show EXIF", parents=[common])
    s.add_argument("id"); s.add_argument("--raw", action="store_true"); s.set_defaults(func=cmd_exif)

    s = sub.add_parser("thumb", help="Show/regen thumbs", parents=[common])
    s.add_argument("id"); s.add_argument("--regenerate", action="store_true")
    s.add_argument("--size", choices=["xs", "sm", "md"]); s.set_defaults(func=cmd_thumb)
