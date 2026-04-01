#!/usr/bin/env python3
"""ComfyUI Studio — Command Line Interface.

Admin and maintenance tool that talks directly to DB and filesystem.
Does NOT go through REST API. Does NOT need the server running.

Usage:
    studio <command> <subcommand> [options]
    studio media stats
    studio media doctor
    studio --help

Entry point: main() at bottom of file.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from textwrap import dedent

# ── Resolve app/ imports ────────────────────────────────────────────────────
# When invoked as `studio` from PATH, we need app/ on sys.path.
# STUDIO_DIR/app/ contains the modules.
_STUDIO_DIR = Path(os.environ.get("STUDIO_DIR", "/workspace/studio"))
_APP_DIR = _STUDIO_DIR / "app"
if str(_APP_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_APP_DIR.parent))


# ── Output helpers ──────────────────────────────────────────────────────────

# ANSI color codes (disabled when piped)
_USE_COLOR = sys.stdout.isatty()

def _c(code: str, text: str) -> str:
    """Wrap text in ANSI color if terminal supports it."""
    if not _USE_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"

def _green(t: str) -> str: return _c("32", t)
def _red(t: str) -> str: return _c("31", t)
def _yellow(t: str) -> str: return _c("33", t)
def _cyan(t: str) -> str: return _c("36", t)
def _dim(t: str) -> str: return _c("2", t)
def _bold(t: str) -> str: return _c("1", t)


def _fmt_bytes(b: int) -> str:
    """Format bytes into human-readable string."""
    if b < 1024:
        return f"{b} B"
    if b < 1024 * 1024:
        return f"{b / 1024:.1f} KB"
    if b < 1024 * 1024 * 1024:
        return f"{b / (1024 * 1024):.1f} MB"
    return f"{b / (1024 * 1024 * 1024):.2f} GB"


def _fmt_date(iso: str) -> str:
    """Format ISO date for display."""
    if not iso:
        return "-"
    # Truncate to seconds if present
    return iso.replace("T", " ").replace("Z", " UTC").strip()


def _table(headers: list[str], rows: list[list[str]], min_widths: list[int] | None = None):
    """Print a formatted table."""
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], len(str(cell)))
    if min_widths:
        for i, mw in enumerate(min_widths):
            if i < len(widths):
                widths[i] = max(widths[i], mw)

    # Header
    header_line = "  ".join(str(h).ljust(widths[i]) for i, h in enumerate(headers))
    print(_bold(header_line))
    print("  ".join("─" * w for w in widths))

    # Rows
    for row in rows:
        cells = []
        for i, cell in enumerate(row):
            s = str(cell)
            if i < len(widths):
                cells.append(s.ljust(widths[i]))
            else:
                cells.append(s)
        print("  ".join(cells))


# ── Media commands ──────────────────────────────────────────────────────────

def _db_conn():
    """Get DB connection for CLI commands."""
    from app.db import get_conn
    return get_conn()


def _get_media_store():
    """Lazy import of media_store module. Initializes DB on first call."""
    from app.db import init_db
    from app import media_store  # importing registers its schema
    init_db()
    return media_store


def cmd_media_stats(args):
    """Show media store statistics.

    Displays total counts, sizes, type breakdown, origin breakdown,
    format distribution, thumbnail coverage, and schema version stats.
    """
    ms = _get_media_store()
    conn = _db_conn()

    # Total counts and sizes
    total = conn.execute("SELECT COUNT(*), COALESCE(SUM(file_size), 0) FROM media").fetchone()
    total_count, total_bytes = total[0], total[1]

    # Thumb stats
    thumb_stats = conn.execute("""
        SELECT size, COUNT(*), COALESCE(SUM(file_size), 0)
        FROM media_thumbs GROUP BY size ORDER BY size
    """).fetchall()
    total_thumb_bytes = sum(r[2] for r in thumb_stats)

    # By type
    by_type = conn.execute("""
        SELECT type, COUNT(*), COALESCE(SUM(file_size), 0)
        FROM media GROUP BY type ORDER BY COUNT(*) DESC
    """).fetchall()

    # By origin
    by_origin = conn.execute("""
        SELECT origin, COUNT(*), COALESCE(SUM(file_size), 0)
        FROM media GROUP BY origin ORDER BY COUNT(*) DESC
    """).fetchall()

    # By format (ext)
    by_format = conn.execute("""
        SELECT ext, COUNT(*), COALESCE(SUM(file_size), 0)
        FROM media GROUP BY ext ORDER BY COUNT(*) DESC
    """).fetchall()

    # Schema version distribution
    by_schema = conn.execute("""
        SELECT schema_version, COUNT(*)
        FROM media GROUP BY schema_version ORDER BY schema_version
    """).fetchall()

    # Thumb coverage
    media_with_thumbs = conn.execute("""
        SELECT COUNT(DISTINCT media_id) FROM media_thumbs
    """).fetchone()[0]

    if args.json:
        print(json.dumps({
            "total_count": total_count,
            "total_bytes": total_bytes,
            "total_thumb_bytes": total_thumb_bytes,
            "total_on_disk": total_bytes + total_thumb_bytes,
            "by_type": {r[0]: {"count": r[1], "bytes": r[2]} for r in by_type},
            "by_origin": {r[0]: {"count": r[1], "bytes": r[2]} for r in by_origin},
            "by_format": {r[0]: {"count": r[1], "bytes": r[2]} for r in by_format},
            "by_schema": {r[0]: r[1] for r in by_schema},
            "thumb_coverage": media_with_thumbs,
            "thumbs": {r[0]: {"count": r[1], "bytes": r[2]} for r in thumb_stats},
        }, indent=2))
        return

    print(_bold("\n  Media Store Statistics\n"))

    # Summary
    print(f"  Total files:     {_cyan(str(total_count))}")
    print(f"  Originals:       {_fmt_bytes(total_bytes)}")
    print(f"  Thumbnails:      {_fmt_bytes(total_thumb_bytes)}")
    print(f"  Total on disk:   {_bold(_fmt_bytes(total_bytes + total_thumb_bytes))}")
    print(f"  Thumb coverage:  {media_with_thumbs}/{total_count} files")

    # By type
    if by_type:
        print(f"\n  {_bold('By type:')}")
        for r in by_type:
            print(f"    {r[0]:10s}  {r[1]:>6d} files  {_fmt_bytes(r[2]):>10s}")

    # By origin
    if by_origin:
        print(f"\n  {_bold('By origin:')}")
        for r in by_origin:
            print(f"    {r[0]:12s}  {r[1]:>6d} files  {_fmt_bytes(r[2]):>10s}")

    # By format
    if by_format:
        print(f"\n  {_bold('By format:')}")
        for r in by_format:
            print(f"    {r[0]:12s}  {r[1]:>6d} files  {_fmt_bytes(r[2]):>10s}")

    # Thumb sizes
    if thumb_stats:
        print(f"\n  {_bold('Thumbnails:')}")
        for r in thumb_stats:
            print(f"    {r[0]:4s}  {r[1]:>6d} thumbs  {_fmt_bytes(r[2]):>10s}")

    # Schema versions
    if by_schema:
        print(f"\n  {_bold('Schema versions:')}")
        current = ms.SCHEMA_VERSION
        for r in by_schema:
            marker = _green("(current)") if r[0] == current else _yellow("(outdated)")
            print(f"    v{r[0]}  {r[1]:>6d} files  {marker}")

    print()


def cmd_media_list(args):
    """List media files with optional filters.

    Supports filtering by type, origin, format, and text search.
    Output is a table by default, JSON with --json flag.
    """
    ms = _get_media_store()
    conn = _db_conn()

    clauses = []
    params = []

    if args.type:
        clauses.append("type = ?")
        params.append(args.type)
    if args.origin:
        clauses.append("origin = ?")
        params.append(args.origin)
    if args.format:
        clauses.append("ext = ?")
        ext = args.format if args.format.startswith(".") else f".{args.format}"
        params.append(ext)
    if args.search:
        clauses.append("(original_name LIKE ? OR origin_id LIKE ? OR id LIKE ?)")
        pat = f"%{args.search}%"
        params.extend([pat, pat, pat])

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sort = args.sort or "created_at"
    order = "DESC" if args.desc else "ASC"
    limit = args.limit or 50
    offset = args.offset or 0

    rows = conn.execute(f"""
        SELECT id, type, ext, original_name, file_size, origin, origin_id, created_at, width, height
        FROM media {where}
        ORDER BY {sort} {order}
        LIMIT ? OFFSET ?
    """, params + [limit, offset]).fetchall()

    total = conn.execute(f"SELECT COUNT(*) FROM media {where}", params).fetchone()[0]

    if args.json:
        print(json.dumps({
            "total": total,
            "showing": len(rows),
            "offset": offset,
            "items": [dict(r) for r in rows],
        }, indent=2))
        return

    if not rows:
        print(_dim("  No media found matching filters."))
        return

    print(f"\n  {_bold(f'Media files')} ({len(rows)} of {total})\n")
    _table(
        ["ID", "Type", "Ext", "Name", "Size", "Origin", "Dimensions", "Created"],
        [
            [
                r["id"][:12] + "...",
                r["type"],
                r["ext"],
                (r["original_name"] or "")[:30],
                _fmt_bytes(r["file_size"]),
                r["origin"],
                f"{r['width']}x{r['height']}" if r["width"] else "-",
                _fmt_date(r["created_at"])[:19],
            ]
            for r in rows
        ],
    )
    if total > offset + limit:
        print(_dim(f"\n  ... {total - offset - limit} more. Use --offset {offset + limit} to see next page."))
    print()


def cmd_media_info(args):
    """Show detailed information about a single media file.

    Displays all properties, thumbnail info, and EXIF data.
    Accepts full ID or prefix (minimum 8 chars).
    """
    ms = _get_media_store()
    conn = _db_conn()

    # Allow prefix match
    media_id = args.id
    if len(media_id) < 32:
        row = conn.execute("SELECT * FROM media WHERE id LIKE ?", (media_id + "%",)).fetchone()
    else:
        row = conn.execute("SELECT * FROM media WHERE id = ?", (media_id,)).fetchone()

    if not row:
        print(_red(f"  Media not found: {media_id}"))
        sys.exit(1)

    m = dict(row)

    if args.json:
        # Parse exif JSON for clean output
        if m.get("exif"):
            try:
                m["exif"] = json.loads(m["exif"])
            except Exception:
                pass
        print(json.dumps(m, indent=2, default=str))
        return

    # Thumbs
    thumbs = conn.execute(
        "SELECT size, file_path, file_size, width, height FROM media_thumbs WHERE media_id = ? ORDER BY file_size",
        (m["id"],)
    ).fetchall()

    # File exists check
    file_path = ms._abs_path(m["file_path"])
    file_exists = file_path.exists()

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
    if m.get("origin_url"):
        print(f"  Origin URL:    {m['origin_url']}")
    print(f"  Created:       {_fmt_date(m.get('created_at', ''))}")

    if thumbs:
        print(f"\n  {_bold('Thumbnails:')}")
        for t in thumbs:
            t_exists = ms._abs_path(t["file_path"]).exists()
            status = _green("✓") if t_exists else _red("✗")
            print(f"    {status} {t['size']:4s}  {t['width']}x{t['height']}  {_fmt_bytes(t['file_size'])}")
    else:
        print(f"\n  {_dim('No thumbnails')}")

    if m.get("exif"):
        print(f"\n  {_bold('EXIF / Embedded metadata:')}")
        try:
            exif = json.loads(m["exif"])
            for k, v in exif.items():
                vs = str(v)
                if len(vs) > 80:
                    vs = vs[:77] + "..."
                print(f"    {k}: {vs}")
        except Exception:
            print(f"    {_dim('(unparseable)')}")
    else:
        print(f"\n  {_dim('No embedded metadata')}")

    print()


def cmd_media_find(args):
    """Search for media by hash, origin, or name pattern.

    At least one search criterion is required.
    Returns matching records in table or JSON format.
    """
    ms = _get_media_store()
    conn = _db_conn()

    if args.hash:
        rows = conn.execute("SELECT * FROM media WHERE hash = ?", (args.hash,)).fetchall()
    elif args.origin and args.origin_id:
        rows = conn.execute(
            "SELECT * FROM media WHERE origin = ? AND origin_id = ?",
            (args.origin, args.origin_id)
        ).fetchall()
    elif args.name:
        rows = conn.execute(
            "SELECT * FROM media WHERE original_name LIKE ?",
            (f"%{args.name}%",)
        ).fetchall()
    else:
        print(_red("  Provide --hash, --origin+--origin-id, or --name"))
        sys.exit(1)

    if args.json:
        print(json.dumps([dict(r) for r in rows], indent=2, default=str))
        return

    if not rows:
        print(_dim("  No matches found."))
        return

    print(f"\n  {_bold(f'Found {len(rows)} match(es)')}\n")
    for r in rows:
        print(f"  {_cyan(r['id'])}")
        print(f"    {r['type']} {r['ext']}  {_fmt_bytes(r['file_size'])}  origin={r['origin']}")
        if r.get("original_name"):
            print(f"    name: {r['original_name']}")
        print()


def cmd_media_doctor(args):
    """Check media store consistency.

    Finds:
    - DB records pointing to missing files on disk
    - Files on disk not tracked in DB (orphans)
    - Thumbnails with missing source media
    - Hash mismatches (optional, slow — use --verify-hashes)
    - Schema version behind current

    Use --fix to auto-resolve issues.
    """
    ms = _get_media_store()
    conn = _db_conn()

    issues = []
    fixed = 0

    print(f"\n  {_bold('Media Store Doctor')}\n")

    # 1. DB records with missing files
    print("  Checking files on disk...", end="", flush=True)
    rows = conn.execute("SELECT id, file_path FROM media").fetchall()
    missing_files = []
    for r in rows:
        if not ms._abs_path(r["file_path"]).exists():
            missing_files.append(r)
    if missing_files:
        print(f" {_red(f'{len(missing_files)} missing')}")
        for r in missing_files:
            issues.append(("missing_file", r["id"], r["file_path"]))
            if args.verbose:
                print(f"    {_red('✗')} {r['id'][:12]}... → {r['file_path']}")
        if args.fix:
            for _, mid, _ in [i for i in issues if i[0] == "missing_file"]:
                conn.execute("DELETE FROM media WHERE id = ?", (mid,))
                fixed += 1
            conn.commit()
            print(f"    {_green(f'Fixed: removed {len(missing_files)} orphan DB records')}")
    else:
        print(f" {_green('all OK')}")

    # 2. Orphan files on disk (not in DB)
    print("  Scanning for orphan files...", end="", flush=True)
    store_dir = ms.MEDIA_STORE_DIR
    orphans = []
    if store_dir.exists():
        db_paths = {r[0] for r in conn.execute("SELECT file_path FROM media").fetchall()}
        thumb_paths = {r[0] for r in conn.execute("SELECT file_path FROM media_thumbs").fetchall()}
        all_known = db_paths | thumb_paths
        for f in store_dir.rglob("*"):
            if f.is_file():
                rel = str(f.relative_to(store_dir))
                if rel not in all_known:
                    orphans.append((rel, f.stat().st_size))
    if orphans:
        total_orphan_bytes = sum(s for _, s in orphans)
        print(f" {_yellow(f'{len(orphans)} orphans ({_fmt_bytes(total_orphan_bytes)})')}")
        for rel, size in orphans:
            issues.append(("orphan_file", rel, size))
            if args.verbose:
                print(f"    {_yellow('?')} {rel} ({_fmt_bytes(size)})")
        if args.fix:
            for _, rel, _ in [i for i in issues if i[0] == "orphan_file"]:
                path = store_dir / rel
                if path.exists():
                    path.unlink()
                    fixed += 1
            conn.commit()
            print(f"    {_green(f'Fixed: removed {len(orphans)} orphan files')}")
    else:
        print(f" {_green('none')}")

    # 3. Missing thumbnails
    print("  Checking thumbnails...", end="", flush=True)
    thumb_rows = conn.execute("SELECT media_id, file_path FROM media_thumbs").fetchall()
    missing_thumbs = []
    for r in thumb_rows:
        if not ms._abs_path(r["file_path"]).exists():
            missing_thumbs.append(r)
    if missing_thumbs:
        print(f" {_yellow(f'{len(missing_thumbs)} missing')}")
        for r in missing_thumbs:
            issues.append(("missing_thumb", r["media_id"], r["file_path"]))
        if args.fix:
            for _, mid, _ in [i for i in issues if i[0] == "missing_thumb"]:
                conn.execute("DELETE FROM media_thumbs WHERE media_id = ? AND file_path = ?", (mid, _))
                fixed += 1
            conn.commit()
            print(f"    {_green(f'Fixed: removed {len(missing_thumbs)} broken thumb records')}")
    else:
        print(f" {_green('all OK')}")

    # 4. Schema version check
    print("  Checking schema versions...", end="", flush=True)
    outdated = conn.execute(
        "SELECT COUNT(*) FROM media WHERE schema_version < ?",
        (ms.SCHEMA_VERSION,)
    ).fetchone()[0]
    if outdated:
        print(f" {_yellow(f'{outdated} outdated (current: v{ms.SCHEMA_VERSION})')}")
        issues.append(("outdated_schema", outdated, ms.SCHEMA_VERSION))
        print(f"    Run {_cyan('studio media reindex')} to update")
    else:
        print(f" {_green('all current')}")

    # 5. Optional: verify hashes
    if args.verify_hashes:
        print("  Verifying file hashes...", end="", flush=True)
        rows = conn.execute("SELECT id, file_path, hash FROM media WHERE hash IS NOT NULL").fetchall()
        mismatches = []
        for i, r in enumerate(rows):
            path = ms._abs_path(r["file_path"])
            if path.exists():
                actual = ms.compute_hash(path)
                if actual != r["hash"]:
                    mismatches.append((r["id"], r["hash"][:16], actual[:16]))
            if (i + 1) % 100 == 0:
                print(f"\r  Verifying file hashes... {i+1}/{len(rows)}", end="", flush=True)
        if mismatches:
            print(f"\r  Verifying file hashes... {_red(f'{len(mismatches)} CORRUPTED')}")
            for mid, expected, actual in mismatches:
                issues.append(("hash_mismatch", mid, f"{expected}→{actual}"))
                print(f"    {_red('✗')} {mid[:12]}... expected={expected}... actual={actual}...")
        else:
            print(f"\r  Verifying file hashes... {_green(f'all OK ({len(rows)} verified)')}")

    # Summary
    print(f"\n  {'─' * 40}")
    if issues:
        print(f"  {_bold(f'{len(issues)} issue(s) found')}")
        if args.fix:
            print(f"  {_green(f'{fixed} fixed')}")
        elif not args.fix:
            print(f"  Run with {_cyan('--fix')} to auto-resolve")
    else:
        print(f"  {_green('No issues found. Media store is healthy.')}")
    print()

    if args.json:
        print(json.dumps({
            "issues": [{"type": t, "id": i, "detail": d} for t, i, d in issues],
            "total_issues": len(issues),
            "fixed": fixed,
        }, indent=2))


def cmd_media_reindex(args):
    """Reprocess metadata, properties, and thumbnails for all media.

    Useful after upgrading the extraction logic (new schema_version).
    By default only processes files with outdated schema_version.
    Use --force to reprocess everything.

    Selective reprocessing:
      --thumbs-only      Only regenerate thumbnails
      --exif-only        Only re-extract EXIF/embedded metadata
      --properties-only  Only re-extract file properties
    """
    ms = _get_media_store()
    conn = _db_conn()

    if args.force:
        rows = conn.execute("SELECT id, file_path, type, ext FROM media").fetchall()
    else:
        rows = conn.execute(
            "SELECT id, file_path, type, ext FROM media WHERE schema_version < ?",
            (ms.SCHEMA_VERSION,)
        ).fetchall()

    total = len(rows)
    if total == 0:
        print(_green("  Everything up to date. Nothing to reindex."))
        return

    print(f"\n  Reindexing {total} files...\n")

    processed = 0
    errors = 0
    import time
    start = time.time()

    for i, r in enumerate(rows):
        media_id = r["id"]
        file_path = ms._abs_path(r["file_path"])

        if not file_path.exists():
            errors += 1
            continue

        try:
            updates = []
            params = []

            # Properties
            if not args.exif_only and not args.thumbs_only:
                props = ms.extract_properties(file_path, r["type"])
                for key in ("width", "height", "duration", "audio", "fps", "codec",
                            "color_space", "bit_depth", "has_alpha"):
                    if key in props:
                        updates.append(f"{key} = ?")
                        params.append(props[key])
                # Also fix file_size
                updates.append("file_size = ?")
                params.append(file_path.stat().st_size)

            # EXIF
            if not args.thumbs_only and not args.properties_only:
                exif = ms.extract_exif(file_path, r["type"])
                updates.append("exif = ?")
                params.append(json.dumps(exif) if exif else None)

            # Thumbnails
            if not args.exif_only and not args.properties_only:
                # Remove old thumbs
                old_thumbs = conn.execute(
                    "SELECT file_path FROM media_thumbs WHERE media_id = ?", (media_id,)
                ).fetchall()
                for ot in old_thumbs:
                    tp = ms._abs_path(ot["file_path"])
                    if tp.exists():
                        tp.unlink()
                conn.execute("DELETE FROM media_thumbs WHERE media_id = ?", (media_id,))

                # Generate new
                thumbs = ms.generate_thumbs(media_id, file_path, r["type"])
                for t in thumbs:
                    conn.execute("""
                        INSERT INTO media_thumbs (media_id, size, file_path, file_size, width, height)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (media_id, t["size"], t["file_path"], t["file_size"], t["width"], t["height"]))

                if thumbs:
                    updates.append("thumb_path = ?")
                    params.append(thumbs[0]["file_path"])
                    updates.append("thumb_size = ?")
                    params.append(thumbs[0]["file_size"])

            # Schema version
            updates.append("schema_version = ?")
            params.append(ms.SCHEMA_VERSION)

            if updates:
                params.append(media_id)
                conn.execute(f"UPDATE media SET {', '.join(updates)} WHERE id = ?", params)

            processed += 1

        except Exception as e:
            errors += 1
            if args.verbose:
                print(f"    {_red('✗')} {media_id[:12]}: {e}")

        # Progress
        if (i + 1) % 10 == 0 or i + 1 == total:
            elapsed = time.time() - start
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            eta = int((total - i - 1) / rate) if rate > 0 else 0
            eta_str = f"{eta}s" if eta < 60 else f"{eta // 60}m{eta % 60}s"
            print(f"\r  [{i+1}/{total}] {rate:.1f}/s  ~{eta_str} left  ", end="", flush=True)

        if (i + 1) % 50 == 0:
            conn.commit()

    conn.commit()
    elapsed = time.time() - start
    print(f"\r  {_green(f'Done: {processed} processed, {errors} errors in {elapsed:.1f}s')}          ")
    print()


def cmd_media_import(args):
    """Import file(s) into the media store.

    Accepts a single file or a directory (with --recursive).
    Each file is validated, hashed, deduplicated, and stored.

    Examples:
        studio media import photo.jpg --origin upload
        studio media import ./images/ --origin civitai --recursive
    """
    ms = _get_media_store()

    source = Path(args.path)
    if not source.exists():
        print(_red(f"  Path not found: {source}"))
        sys.exit(1)

    files = []
    if source.is_file():
        files.append(source)
    elif source.is_dir():
        if not args.recursive:
            print(_red("  Path is a directory. Use --recursive to import all files."))
            sys.exit(1)
        for f in sorted(source.rglob("*")):
            if f.is_file() and f.suffix.lower() in ms.ALLOWED:
                files.append(f)

    if not files:
        print(_dim("  No importable files found."))
        return

    print(f"\n  Importing {len(files)} file(s)...\n")

    imported = 0
    skipped = 0
    errors = 0

    for f in files:
        try:
            # Copy to temp so store() can move it (don't destroy originals)
            import shutil
            import tempfile
            tmp = Path(tempfile.mkdtemp()) / f.name
            shutil.copy2(f, tmp)

            media_id = ms.store(
                tmp,
                origin=args.origin or "upload",
                origin_id=args.origin_id,
                original_name=f.name,
            )
            print(f"  {_green('✓')} {f.name} → {media_id[:12]}...")
            imported += 1
        except ValueError as e:
            if "already in store" in str(e).lower() or ms.hash_exists(ms.compute_hash(f)):
                print(f"  {_dim('=')} {f.name} (duplicate, skipped)")
                skipped += 1
            else:
                print(f"  {_red('✗')} {f.name}: {e}")
                errors += 1
        except Exception as e:
            print(f"  {_red('✗')} {f.name}: {e}")
            errors += 1

    print(f"\n  {_green(f'{imported} imported')}, {skipped} skipped, {errors} errors\n")


def cmd_media_export(args):
    """Export a media file from the store to a destination path.

    Copies the original file (not the sharded version) to the specified
    destination. Use --with-thumbs to also export thumbnails.
    """
    ms = _get_media_store()

    path = ms.serve_path(args.id)
    if not path:
        print(_red(f"  Media not found: {args.id}"))
        sys.exit(1)

    import shutil
    dest = Path(args.dest)

    if dest.is_dir():
        m = ms.get(args.id)
        name = m.get("original_name") or path.name
        dest = dest / name

    shutil.copy2(path, dest)
    print(f"  {_green('✓')} Exported to {dest}")

    if args.with_thumbs:
        thumbs = ms.get_thumbs(args.id)
        for t in thumbs:
            tp = ms._abs_path(t["file_path"])
            if tp.exists():
                thumb_dest = dest.parent / f"{dest.stem}.thumb.{t['size']}{dest.suffix}"
                shutil.copy2(tp, thumb_dest)
                print(f"  {_green('✓')} Thumb {t['size']} → {thumb_dest}")

    print()


def cmd_media_delete(args):
    """Delete one or more media from the store.

    Removes the file, all thumbnails, and the DB record.
    Use --force to skip confirmation.
    """
    ms = _get_media_store()

    ids = args.ids
    if not ids:
        print(_red("  No IDs provided."))
        sys.exit(1)

    # Resolve prefix matches
    resolved = []
    conn = _db_conn()
    for mid in ids:
        if len(mid) < 32:
            row = conn.execute("SELECT id, original_name, file_size FROM media WHERE id LIKE ?", (mid + "%",)).fetchone()
        else:
            row = conn.execute("SELECT id, original_name, file_size FROM media WHERE id = ?", (mid,)).fetchone()
        if row:
            resolved.append(dict(row))
        else:
            print(f"  {_yellow('?')} {mid} — not found, skipping")

    if not resolved:
        return

    # Confirm
    if not args.force:
        print(f"\n  About to delete {len(resolved)} media:\n")
        for r in resolved:
            print(f"    {r['id'][:12]}... {r.get('original_name', '')} ({_fmt_bytes(r['file_size'])})")
        print()
        answer = input("  Continue? [y/N] ").strip().lower()
        if answer != "y":
            print("  Cancelled.")
            return

    deleted = 0
    for r in resolved:
        if ms.delete(r["id"]):
            print(f"  {_green('✓')} Deleted {r['id'][:12]}...")
            deleted += 1
        else:
            print(f"  {_red('✗')} Failed to delete {r['id'][:12]}...")

    print(f"\n  {deleted} deleted.\n")


def cmd_media_verify(args):
    """Verify file integrity by recomputing SHA-256 hashes.

    Compares stored hash with actual file content.
    Use --id to verify a single file, or --all for everything.
    """
    ms = _get_media_store()
    conn = _db_conn()

    if args.id:
        rows = conn.execute("SELECT id, file_path, hash FROM media WHERE id LIKE ?", (args.id + "%",)).fetchall()
    elif args.all:
        rows = conn.execute("SELECT id, file_path, hash FROM media WHERE hash IS NOT NULL").fetchall()
    else:
        print(_red("  Provide --id <prefix> or --all"))
        sys.exit(1)

    if not rows:
        print(_dim("  No files to verify."))
        return

    print(f"\n  Verifying {len(rows)} file(s)...\n")
    ok = 0
    bad = 0
    missing = 0

    import time
    start = time.time()

    for i, r in enumerate(rows):
        path = ms._abs_path(r["file_path"])
        if not path.exists():
            print(f"  {_red('✗')} {r['id'][:12]}... FILE MISSING")
            missing += 1
            continue

        actual = ms.compute_hash(path)
        if actual == r["hash"]:
            ok += 1
            if args.verbose:
                print(f"  {_green('✓')} {r['id'][:12]}...")
        else:
            print(f"  {_red('✗')} {r['id'][:12]}... HASH MISMATCH")
            print(f"      expected: {r['hash'][:32]}...")
            print(f"      actual:   {actual[:32]}...")
            bad += 1

        if (i + 1) % 50 == 0:
            elapsed = time.time() - start
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            print(f"\r  [{i+1}/{len(rows)}] {rate:.1f}/s", end="", flush=True)

    elapsed = time.time() - start
    print(f"\n  {_green(f'{ok} OK')}, {_red(f'{bad} corrupted') if bad else '0 corrupted'}, {missing} missing ({elapsed:.1f}s)\n")


def cmd_media_dedup(args):
    """Find duplicate media files (same SHA-256 hash).

    Shows groups of files with identical content.
    Use --dry-run to preview without changes.
    """
    ms = _get_media_store()
    conn = _db_conn()

    dupes = conn.execute("""
        SELECT hash, COUNT(*) as cnt, GROUP_CONCAT(id, ',') as ids
        FROM media
        WHERE hash IS NOT NULL
        GROUP BY hash
        HAVING cnt > 1
        ORDER BY cnt DESC
    """).fetchall()

    if not dupes:
        print(_green("  No duplicates found."))
        return

    total_waste = 0
    print(f"\n  {_bold(f'{len(dupes)} duplicate group(s)')}\n")

    for d in dupes:
        ids = d["ids"].split(",")
        rows = conn.execute(
            f"SELECT id, original_name, file_size, origin, created_at FROM media WHERE id IN ({','.join('?' * len(ids))})",
            ids
        ).fetchall()

        print(f"  Hash: {d['hash'][:24]}... ({d['cnt']} copies)")
        for r in rows:
            print(f"    {r['id'][:12]}... {r['original_name'] or '-':30s} {_fmt_bytes(r['file_size']):>10s}  {r['origin']}")
        waste = rows[0]["file_size"] * (len(rows) - 1)
        total_waste += waste
        print(f"    {_dim(f'Wasted: {_fmt_bytes(waste)}')}")
        print()

    print(f"  Total wasted space: {_yellow(_fmt_bytes(total_waste))}")
    if not args.dry_run:
        print(f"  {_dim('(dedup merge not yet implemented — showing report only)')}")
    print()


def cmd_media_exif(args):
    """Show embedded metadata (EXIF/PNG chunks/ffprobe tags) for a media file.

    The --raw flag shows the full JSON as stored in the database.
    """
    ms = _get_media_store()
    conn = _db_conn()

    media_id = args.id
    if len(media_id) < 32:
        row = conn.execute("SELECT id, exif, type, original_name FROM media WHERE id LIKE ?", (media_id + "%",)).fetchone()
    else:
        row = conn.execute("SELECT id, exif, type, original_name FROM media WHERE id = ?", (media_id,)).fetchone()

    if not row:
        print(_red(f"  Media not found: {media_id}"))
        sys.exit(1)

    if not row["exif"]:
        print(_dim(f"  No embedded metadata for {row['id'][:12]}... ({row.get('original_name', '')})"))
        return

    exif = json.loads(row["exif"])

    if args.raw or args.json:
        print(json.dumps(exif, indent=2, default=str))
        return

    print(f"\n  {_bold('Embedded metadata')} for {row['id'][:12]}...\n")
    print(f"  Source: {_cyan(exif.get('_source', 'unknown'))}")
    print()

    for k, v in exif.items():
        if k.startswith("_"):
            continue
        vs = str(v)
        if len(vs) > 100:
            vs = vs[:97] + "..."
        print(f"  {_dim(k + ':'):30s} {vs}")

    print()


def cmd_media_thumb(args):
    """Show or regenerate thumbnails for a media file.

    Without --regenerate, shows current thumbnail info.
    With --regenerate, removes old thumbs and generates new ones.
    Use --size to regenerate only a specific size (xs, sm, md).
    """
    ms = _get_media_store()
    conn = _db_conn()

    media_id = args.id
    if len(media_id) < 32:
        row = conn.execute("SELECT * FROM media WHERE id LIKE ?", (media_id + "%",)).fetchone()
    else:
        row = conn.execute("SELECT * FROM media WHERE id = ?", (media_id,)).fetchone()

    if not row:
        print(_red(f"  Media not found: {media_id}"))
        sys.exit(1)

    m = dict(row)
    file_path = ms._abs_path(m["file_path"])

    if not args.regenerate:
        # Show current thumbs
        thumbs = ms.get_thumbs(m["id"])
        if not thumbs:
            print(_dim(f"  No thumbnails for {m['id'][:12]}..."))
        else:
            print(f"\n  {_bold('Thumbnails')} for {m['id'][:12]}...\n")
            for t in thumbs:
                exists = ms._abs_path(t["file_path"]).exists()
                status = _green("✓") if exists else _red("✗ MISSING")
                print(f"  {status}  {t['size']:4s}  {t['width']}x{t['height']}  {_fmt_bytes(t['file_size'])}  {t['file_path']}")
        print()
        return

    # Regenerate
    if not file_path.exists():
        print(_red(f"  Original file missing: {m['file_path']}"))
        sys.exit(1)

    # Remove old
    old_thumbs = conn.execute("SELECT file_path FROM media_thumbs WHERE media_id = ?", (m["id"],)).fetchall()
    for ot in old_thumbs:
        tp = ms._abs_path(ot["file_path"])
        if tp.exists():
            tp.unlink()
    conn.execute("DELETE FROM media_thumbs WHERE media_id = ?", (m["id"],))

    # Generate
    if args.size:
        # Single size
        max_side = ms.THUMB_SIZES.get(args.size)
        if not max_side:
            print(_red(f"  Unknown size: {args.size}. Use xs, sm, or md."))
            sys.exit(1)
        thumbs = []
        rel = f"{ms._shard_dir(m['id'])}/{m['id']}.thumb.{args.size}.jpg"
        dest = ms._abs_path(rel)
        if m["type"] == "image":
            ok = ms._generate_image_thumb(file_path, dest, max_side)
        else:
            ok = ms._generate_video_thumb(file_path, dest, max_side)
        if ok:
            from PIL import Image
            img = Image.open(dest)
            thumbs.append({"size": args.size, "file_path": rel, "file_size": dest.stat().st_size,
                           "width": img.width, "height": img.height})
            img.close()
    else:
        thumbs = ms.generate_thumbs(m["id"], file_path, m["type"])

    for t in thumbs:
        conn.execute("""
            INSERT INTO media_thumbs (media_id, size, file_path, file_size, width, height)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (m["id"], t["size"], t["file_path"], t["file_size"], t["width"], t["height"]))

    if thumbs:
        conn.execute("UPDATE media SET thumb_path = ?, thumb_size = ? WHERE id = ?",
                     (thumbs[0]["file_path"], thumbs[0]["file_size"], m["id"]))

    conn.commit()

    print(f"  {_green(f'Generated {len(thumbs)} thumbnail(s)')}")
    for t in thumbs:
        print(f"    {t['size']:4s}  {t['width']}x{t['height']}  {_fmt_bytes(t['file_size'])}")
    print()


# ── Argument parser ─────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    """Build the complete argument parser with all commands and subcommands."""

    parser = argparse.ArgumentParser(
        prog="studio",
        description="ComfyUI Studio — Admin and maintenance CLI",
        epilog="Run 'studio <command> --help' for command-specific help.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version="%(prog)s 0.1.0")
    parser.add_argument("--json", action="store_true", help="Output in JSON format")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    subparsers = parser.add_subparsers(dest="command", title="commands")

    # ── media ──

    # Common arguments shared by all subcommands
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="Output in JSON format")
    common.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    media_parser = subparsers.add_parser(
        "media",
        help="Media store operations",
        description=dedent("""\
            Manage the centralised media file store.

            The media store holds all images and videos in the system:
            gallery images, job outputs, user uploads, preset thumbnails.
            Every file is validated, hashed, and tracked in SQLite.

            Files are stored in a sharded flat directory (STUDIO_DIR/media/)
            with thumbnails at three sizes (xs=100px, sm=200px, md=400px).
        """),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    media_sub = media_parser.add_subparsers(dest="subcommand", title="subcommands")

    # media stats
    p = media_sub.add_parser("stats", help="Show store statistics", parents=[common],
                             description="Display total counts, sizes, breakdowns by type/origin/format, thumbnail coverage.")
    p.set_defaults(func=cmd_media_stats)

    # media list
    p = media_sub.add_parser("list", help="List media files", parents=[common],
                             description="List media with optional filters. Supports pagination.")
    p.add_argument("--type", choices=["image", "video"], help="Filter by media type")
    p.add_argument("--origin", help="Filter by origin (civitai, comfyui, upload)")
    p.add_argument("--format", help="Filter by format/extension (jpeg, png, mp4, ...)")
    p.add_argument("--search", "-s", help="Search in name, origin_id, or ID")
    p.add_argument("--sort", default="created_at",
                   help="Sort field (created_at, file_size, type, origin). Default: created_at")
    p.add_argument("--desc", action="store_true", help="Sort descending")
    p.add_argument("--limit", type=int, default=50, help="Max results (default: 50)")
    p.add_argument("--offset", type=int, default=0, help="Skip first N results")
    p.set_defaults(func=cmd_media_list)

    # media info
    p = media_sub.add_parser("info", help="Detailed info about a media file", parents=[common],
                             description="Show all properties, thumbnails, and EXIF for a single media. Accepts full ID or prefix (min 8 chars).")
    p.add_argument("id", help="Media ID (full or prefix)")
    p.set_defaults(func=cmd_media_info)

    # media find
    p = media_sub.add_parser("find", help="Search media by hash, origin, or name", parents=[common],
                             description="Find media matching specific criteria. At least one search parameter required.")
    p.add_argument("--hash", help="Find by SHA-256 hash")
    p.add_argument("--origin", help="Find by origin (use with --origin-id)")
    p.add_argument("--origin-id", help="Find by origin ID (use with --origin)")
    p.add_argument("--name", help="Search in original filename (substring match)")
    p.set_defaults(func=cmd_media_find)

    # media doctor
    p = media_sub.add_parser("doctor", help="Check store consistency", parents=[common],
                             description=dedent("""\
                                 Diagnose issues in the media store:
                                 - DB records pointing to missing files
                                 - Orphan files on disk (not in DB)
                                 - Missing thumbnails
                                 - Outdated schema versions
                                 - Hash mismatches (with --verify-hashes)
                             """),
                             formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--fix", action="store_true", help="Auto-fix found issues")
    p.add_argument("--verify-hashes", action="store_true", help="Recompute and verify all hashes (slow)")
    p.set_defaults(func=cmd_media_doctor)

    # media reindex
    p = media_sub.add_parser("reindex", help="Reprocess metadata and thumbnails", parents=[common],
                             description=dedent("""\
                                 Re-extract properties, EXIF, and thumbnails for media files.
                                 By default only processes files with outdated schema_version.
                                 Use --force to reprocess everything.
                             """),
                             formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--force", action="store_true", help="Reprocess all files, not just outdated")
    p.add_argument("--thumbs-only", action="store_true", help="Only regenerate thumbnails")
    p.add_argument("--exif-only", action="store_true", help="Only re-extract EXIF metadata")
    p.add_argument("--properties-only", action="store_true", help="Only re-extract file properties")
    p.set_defaults(func=cmd_media_reindex)

    # media import
    p = media_sub.add_parser("import", help="Import files into the store", parents=[common],
                             description="Import a file or directory into the media store. Files are validated, hashed, and stored.",
                             epilog="Examples:\n  studio media import photo.jpg --origin upload\n  studio media import ./gallery/ --origin civitai --recursive",
                             formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("path", help="File or directory to import")
    p.add_argument("--origin", default="upload", help="Origin label (default: upload)")
    p.add_argument("--origin-id", help="Origin ID (e.g., CivitAI image ID)")
    p.add_argument("--recursive", "-r", action="store_true", help="Import all files in directory recursively")
    p.set_defaults(func=cmd_media_import)

    # media export
    p = media_sub.add_parser("export", help="Export a media file from the store", parents=[common],
                             description="Copy the original file to a destination. Optionally include thumbnails.")
    p.add_argument("id", help="Media ID")
    p.add_argument("dest", help="Destination path (file or directory)")
    p.add_argument("--with-thumbs", action="store_true", help="Also export thumbnails")
    p.set_defaults(func=cmd_media_export)

    # media delete
    p = media_sub.add_parser("delete", help="Delete media from the store", parents=[common],
                             description="Remove files, thumbnails, and DB records. Asks for confirmation unless --force.")
    p.add_argument("ids", nargs="+", help="Media ID(s) to delete (full or prefix)")
    p.add_argument("--force", "-f", action="store_true", help="Skip confirmation")
    p.set_defaults(func=cmd_media_delete)

    # media verify
    p = media_sub.add_parser("verify", help="Verify file integrity via hash check", parents=[common],
                             description="Recompute SHA-256 and compare with stored hash. Reports corrupted files.")
    p.add_argument("--id", help="Verify single file (ID or prefix)")
    p.add_argument("--all", action="store_true", help="Verify all files")
    p.set_defaults(func=cmd_media_verify)

    # media dedup
    p = media_sub.add_parser("dedup", help="Find duplicate files", parents=[common],
                             description="Find media files with identical SHA-256 hashes. Shows wasted space.")
    p.add_argument("--dry-run", action="store_true", help="Show report without making changes")
    p.set_defaults(func=cmd_media_dedup)

    # media exif
    p = media_sub.add_parser("exif", help="Show embedded metadata", parents=[common],
                             description="Display EXIF tags, PNG text chunks, or ffprobe metadata extracted from the file.")
    p.add_argument("id", help="Media ID (full or prefix)")
    p.add_argument("--raw", action="store_true", help="Show full JSON as stored")
    p.set_defaults(func=cmd_media_exif)

    # media thumb
    p = media_sub.add_parser("thumb", help="Show or regenerate thumbnails", parents=[common],
                             description="Display thumbnail info for a media file, or regenerate with --regenerate.")
    p.add_argument("id", help="Media ID (full or prefix)")
    p.add_argument("--regenerate", action="store_true", help="Regenerate thumbnails")
    p.add_argument("--size", choices=["xs", "sm", "md"], help="Regenerate only this size")
    p.set_defaults(func=cmd_media_thumb)

    return parser


# ── Entry point ─────────────────────────────────────────────────────────────

def main():
    """Main entry point for the studio CLI."""
    parser = build_parser()
    args = parser.parse_args()

    # Propagate global flags
    if not hasattr(args, "json"):
        args.json = False
    if not hasattr(args, "verbose"):
        args.verbose = False

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == "media" and not args.subcommand:
        # Show media help
        parser.parse_args(["media", "--help"])
        sys.exit(0)

    if hasattr(args, "func"):
        try:
            args.func(args)
        except KeyboardInterrupt:
            print("\n  Interrupted.")
            sys.exit(130)
        except Exception as e:
            print(f"\n  {_red(f'Error: {e}')}")
            if args.verbose:
                import traceback
                traceback.print_exc()
            sys.exit(1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
