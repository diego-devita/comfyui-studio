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

# ── Resolve imports ──────────────────────────────────────────────────────────
# When invoked via bin/studio, the project root must be on sys.path
# so that "from v2.app.xxx" imports work. The bin/studio launcher handles this.


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

_initialized = False

def _init():
    """Initialize all modules and DB. Called once, idempotent."""
    global _initialized
    if _initialized:
        return
    from v2.app import media_store        # registers schema
    from v2.app import model_store        # registers schema
    from v2.app import catalog            # registers schema
    from v2.app import download_scheduler # registers schema
    from v2.app import gallery            # registers schema + callback
    from v2.app.db import init_db
    init_db()
    _initialized = True


def _db_conn():
    """Get DB connection for CLI commands."""
    _init()
    from v2.app.db import get_conn
    return get_conn()


def _get_media_store():
    """Get media_store module (initializes DB on first call)."""
    _init()
    from v2.app import media_store
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


# ── Catalog commands ─────────────────────────────────────────────────────────

def _get_catalog():
    _init()
    from v2.app import catalog
    return catalog


def cmd_catalog_stats(args):
    """Show catalog statistics."""
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


def cmd_catalog_list(args):
    """List models with optional filters."""
    cat = _get_catalog()
    models = cat.find_models(
        name=args.search,
        category=args.category,
        type=args.type,
        limit=args.limit,
        offset=args.offset,
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


def cmd_catalog_info(args):
    """Show detailed info about a model."""
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
        print(f"  Source:   {s['source']} → {s['source_id']}" + (f"  {s['source_url']}" if s.get("source_url") else ""))
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


def cmd_catalog_import(args):
    """Import a model from CivitAI (upsert)."""
    from v2.app.civitai_client import CivitaiClient
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
    total_versions = len(data.get("modelVersions", []))
    print(f"  Type: {data.get('type')}  Versions: {total_versions}")

    version_ids = None
    if args.versions:
        version_ids = [int(v) for v in args.versions.split(",")]
        print(f"  Importing only versions: {version_ids}")

    result = cat.import_from_civitai(
        civitai_data=data,
        version_ids=version_ids,
        category=args.category,
    )

    print(f"\n  {_green('Done:')}")
    print(f"    Model ID:        {result['model_id'][:12]}...")
    print(f"    Versions created: {result['versions_created']}")
    print(f"    Versions skipped: {result['versions_skipped']}")
    print(f"    Files created:    {result['files_created']}")
    print()


def cmd_catalog_versions(args):
    """List versions of a model."""
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


def cmd_catalog_files(args):
    """List files of a version."""
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


# ── Download commands ────────────────────────────────────────────────────────

def _get_scheduler():
    _init()
    from v2.app import download_scheduler
    return download_scheduler


def cmd_download_list(args):
    """List downloads."""
    dl = _get_scheduler()
    if args.active:
        rows = dl.list_active()
    else:
        rows = dl.list_all(limit=args.limit)
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


def cmd_download_status(args):
    """Show download status."""
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


def cmd_download_cancel(args):
    """Cancel a download."""
    dl = _get_scheduler()
    if dl.cancel(args.id):
        print(f"  {_green('Cancelled')} {args.id}")
    else:
        print(_red(f"  Not found or already terminal: {args.id}"))


def cmd_download_retry(args):
    """Retry a failed download."""
    dl = _get_scheduler()
    if dl.retry(args.id):
        print(f"  {_green('Requeued')} {args.id}")
    else:
        print(_red(f"  Not found or not in retryable state: {args.id}"))


def cmd_download_cleanup(args):
    """Clean up temp download files."""
    dl = _get_scheduler()
    removed = dl.cleanup_temp()
    print(f"  {_green(f'{removed} temp file(s) removed')}")


def cmd_download_queue(args):
    """Show queue statistics."""
    dl = _get_scheduler()
    q = dl.queue_size()
    if args.json:
        print(json.dumps(q, indent=2))
        return
    print(f"\n  {_bold('Download Queue')}\n")
    for status, count in q.items():
        print(f"  {status:15s} {count}")
    print()


# ── Gallery commands ─────────────────────────────────────────────────────────

def _get_gallery():
    _init()
    from v2.app import gallery
    return gallery


def cmd_gallery_stats(args):
    """Show total gallery statistics (card + community counts and sizes)."""
    g = _get_gallery()
    s = g.get_gallery_stats()
    if args.json:
        print(json.dumps(s, indent=2))
        return
    print(f"\n  {_bold('Gallery Statistics')}\n")
    print(f"  Card images:      {s['card_count']:>6d}  ({_fmt_bytes(s['card_bytes'])})")
    print(f"  Community images: {s['community_count']:>6d}  ({_fmt_bytes(s['community_bytes'])})")
    print(f"  Total:            {s['total_count']:>6d}  ({_fmt_bytes(s['total_bytes'])})")
    print()


def cmd_gallery_status(args):
    """Show gallery status for models/versions in the catalog."""
    g = _get_gallery()
    cat = _get_catalog()
    conn = _db_conn()

    # Single model or single version
    if args.model_id:
        m = cat.get_model(args.model_id)
        if not m:
            print(_red(f"  Model not found: {args.model_id}"))
            sys.exit(1)

        gal = g.get_model_gallery(m["id"])

        if args.version:
            # Single version
            v_count = gal["versions"].get(args.version, {})
            if args.json:
                print(json.dumps({"model_id": m["id"], "version_id": args.version, **v_count}, indent=2))
                return
            print(f"\n  {m['name']} / version {args.version[:12]}...")
            print(f"  Community: {v_count.get('count', 0)} images ({_fmt_bytes(v_count.get('bytes', 0))})")
            print()
            return

        # Whole model
        if args.json:
            print(json.dumps({"model_id": m["id"], "name": m["name"], **gal}, indent=2, default=str))
            return
        print(f"\n  {_bold(m['name'])}\n")
        print(f"  Card images: {gal['card_count']} ({_fmt_bytes(gal['card_bytes'])})")
        versions = cat.get_versions_by_model(m["id"])
        for v in versions:
            vc = gal["versions"].get(v["id"], {})
            count = vc.get("count", 0)
            vbytes = vc.get("bytes", 0)
            print(f"    {v['name']:35s}  {count:>5d} community  ({_fmt_bytes(vbytes)})")
        print()
        return

    # All models
    models = cat.find_models(limit=500)
    rows = []
    for m in models:
        gal = g.get_model_gallery(m["id"])
        card_count = gal["card_count"]
        comm_count = gal["community_count"]
        if args.empty and (card_count > 0 or comm_count > 0):
            continue
        if not args.empty or (card_count == 0 and comm_count == 0):
            rows.append({
                "model_id": m["id"], "name": m["name"],
                "card": card_count, "community": comm_count,
                "card_bytes": gal["card_bytes"], "community_bytes": gal["community_bytes"],
            })

    if args.json:
        print(json.dumps(rows, indent=2))
        return
    if not rows:
        print(_dim("  No models match."))
        return
    print(f"\n  {_bold('Gallery Status')}\n")
    _table(
        ["Model", "Card", "Community", "Total Size"],
        [[r["name"][:40], str(r["card"]), str(r["community"]),
          _fmt_bytes(r["card_bytes"] + r["community_bytes"])] for r in rows],
    )
    total_card = sum(r["card"] for r in rows)
    total_comm = sum(r["community"] for r in rows)
    print(f"\n  {len(rows)} models, {total_card} card, {total_comm} community")
    print()


def cmd_gallery_download(args):
    """Download gallery images for a model."""
    g = _get_gallery()
    cat = _get_catalog()
    from v2.app.settings import CIVITAI_API_KEY
    import time as _time

    api_key = CIVITAI_API_KEY
    if not api_key:
        print(_red("  CIVITAI_API_KEY not set."))
        sys.exit(1)

    # Interactive mode: no model_id given
    if not args.model_id:
        models = cat.find_models(limit=100)
        if not models:
            print(_dim("  Catalog is empty. Import models first with 'studio catalog import'."))
            return
        print(f"\n  {_bold('Choose a model:')}\n")
        for i, m in enumerate(models):
            print(f"  {i+1:3d}. {m['name'][:50]}  ({m.get('category') or '?'})")
        print()
        try:
            choice = int(input("  Number: ").strip()) - 1
            if choice < 0 or choice >= len(models):
                print("  Cancelled.")
                return
        except (ValueError, EOFError):
            print("  Cancelled.")
            return
        selected_model = models[choice]
    else:
        selected_model = cat.get_model(args.model_id)
        if not selected_model:
            print(_red(f"  Model not found: {args.model_id}"))
            sys.exit(1)

    model_id = selected_model["id"]
    model_name = selected_model["name"]

    # Get CivitAI model ID from source mappings
    source = cat.get_by_source_entity("model", model_id)
    if not source:
        print(_red(f"  No CivitAI source for model '{model_name}'. Only CivitAI models supported."))
        sys.exit(1)
    civitai_model_id = int(source["source_id"])

    # Determine what to download
    job_ids = []

    if args.cards or args.all:
        print(f"\n  Downloading card images for {_cyan(model_name)}...")
        jid = g.download_card_images(model_id, civitai_model_id, api_key)
        if jid:
            job_ids.append(("card", jid))
            print(f"  Job: {jid[:12]}...")
        else:
            print(_dim("  No card images found."))

    if args.version:
        # Community for specific version
        version = cat.get_version(args.version)
        if not version:
            print(_red(f"  Version not found: {args.version}"))
            sys.exit(1)
        vs = cat.get_by_source_entity("version", args.version)
        if not vs:
            print(_red(f"  No CivitAI source for version."))
            sys.exit(1)
        civitai_vid = int(vs["source_id"])
        print(f"  Downloading community for {_cyan(version['name'])}...")
        jid = g.download_community_images(model_id, args.version, civitai_vid, api_key)
        if jid:
            job_ids.append(("community", jid))
            print(f"  Job: {jid[:12]}...")
        else:
            print(_dim("  No community images found."))

    elif args.all:
        # Community for ALL versions
        versions = cat.get_versions_by_model(model_id)
        for v in versions:
            vs = cat.get_by_source_entity("version", v["id"])
            if not vs:
                continue
            civitai_vid = int(vs["source_id"])
            print(f"  Downloading community for {_cyan(v['name'])}...")
            jid = g.download_community_images(model_id, v["id"], civitai_vid, api_key)
            if jid:
                job_ids.append(("community", jid))
                print(f"  Job: {jid[:12]}...")

    elif not args.cards:
        # Interactive: ask what to download
        print(f"\n  Model: {_bold(model_name)}")
        versions = cat.get_versions_by_model(model_id)
        print(f"  Versions: {len(versions)}\n")
        print("  What to download?")
        print("    1. Card images only")
        print("    2. Community images (choose version)")
        print("    3. Everything (cards + community all versions)")
        print()
        try:
            choice = input("  Choice [1/2/3]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("  Cancelled.")
            return

        if choice == "1":
            jid = g.download_card_images(model_id, civitai_model_id, api_key)
            if jid:
                job_ids.append(("card", jid))
        elif choice == "2":
            for i, v in enumerate(versions):
                print(f"    {i+1}. {v['name']}")
            try:
                vi = int(input("  Version: ").strip()) - 1
            except (ValueError, EOFError):
                print("  Cancelled.")
                return
            if vi < 0 or vi >= len(versions):
                print("  Cancelled.")
                return
            v = versions[vi]
            vs = cat.get_by_source_entity("version", v["id"])
            if vs:
                jid = g.download_community_images(model_id, v["id"], int(vs["source_id"]), api_key)
                if jid:
                    job_ids.append(("community", jid))
        elif choice == "3":
            jid = g.download_card_images(model_id, civitai_model_id, api_key)
            if jid:
                job_ids.append(("card", jid))
            for v in versions:
                vs = cat.get_by_source_entity("version", v["id"])
                if vs:
                    jid = g.download_community_images(model_id, v["id"], int(vs["source_id"]), api_key)
                    if jid:
                        job_ids.append(("community", jid))

    if not job_ids:
        print(_dim("\n  Nothing to download."))
        return

    # Background mode: just print IDs and exit
    if args.background:
        print(f"\n  {_green(f'{len(job_ids)} job(s) started in background:')}")
        for jtype, jid in job_ids:
            print(f"    {jtype}: {jid[:12]}...")
        print(f"\n  Monitor: studio gallery jobs")
        print()
        return

    # Live monitoring mode: poll and show progress
    print(f"\n  {_bold(f'Monitoring {len(job_ids)} job(s)...')}  (Ctrl+C to detach)\n")
    try:
        while True:
            all_done = True
            for jtype, jid in job_ids:
                j = g.get_job_status(jid)
                if j is None:
                    # Job completed and auto-deleted
                    print(f"\r  {_green('✓')} {jtype}: completed                              ")
                    continue
                all_done = False
                total = j["total"] or 0
                completed = j["completed"]
                failed = j["failed"]
                pct = (completed / total * 100) if total > 0 else 0
                bar_w = 30
                filled = int(bar_w * pct / 100)
                bar = "█" * filled + "░" * (bar_w - filled)
                fail_str = f"  {_red(f'{failed} failed')}" if failed else ""
                print(f"\r  [{bar}] {completed}/{total} {pct:.0f}%  {jtype}{fail_str}    ", end="", flush=True)

            if all_done:
                print(f"\n\n  {_green('All done.')}")
                break
            _time.sleep(1)

    except KeyboardInterrupt:
        print(f"\n\n  Detached. Jobs continue in background.")
        print(f"  Monitor: studio gallery jobs")
        for _, jid in job_ids:
            print(f"  Stop:    studio gallery stop {jid[:12]}")
        print()


def cmd_gallery_jobs(args):
    """List active gallery jobs (snapshot)."""
    g = _get_gallery()
    jobs = g.list_active_jobs()
    if args.json:
        print(json.dumps(jobs, indent=2, default=str))
        return
    if not jobs:
        print(_dim("  No active gallery jobs."))
        return
    print(f"\n  {_bold(f'Gallery Jobs ({len(jobs)})')}\n")
    _table(
        ["ID", "Type", "Status", "Progress", "Failed", "Created"],
        [[j["id"][:12] + "...", j["image_type"], j["status"],
          f"{j['completed']}/{j['total']}", str(j["failed"]),
          _fmt_date(j["created_at"])[:16]] for j in jobs],
    )
    print()


def cmd_gallery_job(args):
    """Monitor a gallery job. Live by default, snapshot with --json."""
    g = _get_gallery()
    import time as _time

    j = g.get_job_status(args.id)
    if not j:
        print(_green("  Job completed (or not found)."))
        return

    if args.json:
        print(json.dumps(j, indent=2, default=str))
        return

    # Live monitoring
    print(f"\n  {_bold('Gallery Job')} {_cyan(j['id'][:12])}...  (Ctrl+C to exit)\n")
    try:
        while True:
            j = g.get_job_status(args.id)
            if j is None:
                print(f"\r  {_green('Completed.')}                                     ")
                break
            total = j["total"] or 0
            completed = j["completed"]
            failed = j["failed"]
            pct = (completed / total * 100) if total > 0 else 0
            bar_w = 40
            filled = int(bar_w * pct / 100)
            bar = "█" * filled + "░" * (bar_w - filled)
            fail_str = f"  {_red(f'{failed} failed')}" if failed else ""
            print(f"\r  [{bar}] {completed}/{total} {pct:.0f}%  {j['status']}{fail_str}    ", end="", flush=True)
            if j["status"] in ("error",):
                print(f"\n  {_red('Job failed.')}")
                break
            _time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n  Exited monitoring. Job continues.")
    print()


def cmd_gallery_stop(args):
    """Stop a running gallery job."""
    g = _get_gallery()
    g.stop_job(args.id)
    print(f"  {_green('Stop signal sent')} for {args.id[:12]}...")


def cmd_gallery_cleanup(args):
    """Clean up interrupted/failed gallery jobs with a report."""
    g = _get_gallery()
    cat = _get_catalog()
    conn = _db_conn()

    rows = conn.execute("""
        SELECT * FROM gallery_jobs WHERE status IN ('interrupted', 'error')
        ORDER BY created_at DESC
    """).fetchall()

    if not rows:
        print(_green("  No interrupted or failed gallery jobs."))
        return

    if args.json:
        print(json.dumps([dict(r) for r in rows], indent=2, default=str))
        return

    print(f"\n  {_bold(f'Gallery jobs to clean up ({len(rows)})')}\n")
    for r in rows:
        m = cat.get_model(r["model_id"])
        model_name = m["name"][:35] if m else "?"
        total = r["total"] or 0
        completed = r["completed"]
        failed = r["failed"]
        never_started = max(0, total - completed - failed)
        print(f"  {r['id'][:12]}...  {r['status']:12s}  {model_name}")
        print(f"    {r['image_type']}  {completed}/{total} done, {failed} failed, {never_started} never started")
        print(f"    created: {_fmt_date(r['created_at'])}")
        print()

    if args.force:
        pass  # skip confirmation
    else:
        try:
            answer = input(f"  Delete {len(rows)} job(s)? [y/N] ").strip().lower()
            if answer != "y":
                print("  Cancelled.")
                return
        except (EOFError, KeyboardInterrupt):
            print("\n  Cancelled.")
            return

    conn.execute("DELETE FROM gallery_jobs WHERE status IN ('interrupted', 'error')")
    conn.commit()
    print(f"  {_green(f'{len(rows)} job(s) cleaned up.')}")


def cmd_gallery_resume(args):
    """Resume interrupted gallery jobs."""
    g = _get_gallery()
    cat = _get_catalog()
    from v2.app.settings import CIVITAI_API_KEY
    from v2.app.civitai_client import CivitaiClient
    import time as _time

    api_key = CIVITAI_API_KEY
    if not api_key:
        print(_red("  CIVITAI_API_KEY not set."))
        sys.exit(1)

    conn = _db_conn()

    if args.job_id:
        # Resume specific job
        rows = conn.execute(
            "SELECT * FROM gallery_jobs WHERE id = ? AND status = 'interrupted'",
            (args.job_id,)
        ).fetchall()
        if not rows:
            print(_red(f"  Job not found or not interrupted: {args.job_id}"))
            sys.exit(1)
    elif args.all:
        rows = conn.execute(
            "SELECT * FROM gallery_jobs WHERE status = 'interrupted'"
        ).fetchall()
    else:
        # Interactive: list and choose
        rows = conn.execute(
            "SELECT * FROM gallery_jobs WHERE status = 'interrupted' ORDER BY created_at DESC"
        ).fetchall()
        if not rows:
            print(_green("  No interrupted jobs to resume."))
            return
        print(f"\n  {_bold('Interrupted gallery jobs:')}\n")
        for i, r in enumerate(rows):
            m = cat.get_model(r["model_id"])
            mname = m["name"][:40] if m else "?"
            print(f"  {i+1:3d}. {r['id'][:12]}... {mname}  {r['image_type']}  {r['completed']}/{r['total']}")
        print()
        try:
            choice = input("  Resume which? (number, 'all', or Enter to cancel): ").strip()
            if choice.lower() == "all":
                pass  # resume all
            elif choice == "":
                print("  Cancelled.")
                return
            else:
                idx = int(choice) - 1
                if idx < 0 or idx >= len(rows):
                    print("  Cancelled.")
                    return
                rows = [rows[idx]]
        except (ValueError, EOFError, KeyboardInterrupt):
            print("\n  Cancelled.")
            return

    if not rows:
        print(_green("  No interrupted jobs to resume."))
        return

    job_ids = []
    for r in rows:
        r = dict(r)
        model_id = r["model_id"]
        version_id = r.get("version_id")
        image_type = r["image_type"]
        job_id = r["id"]
        total = r["total"] or 0
        completed = r["completed"]
        filters = json.loads(r.get("filters") or "{}")

        m = cat.get_model(model_id)
        mname = m["name"][:40] if m else "?"
        print(f"\n  Resuming {_cyan(mname)} ({image_type}) — {completed}/{total} already done...")

        # Get CivitAI IDs
        model_source = cat.get_by_source_entity("model", model_id)
        if not model_source:
            print(_red(f"    No CivitAI source for model. Skipping."))
            continue
        civitai_model_id = int(model_source["source_id"])

        # Set job back to running
        conn.execute("UPDATE gallery_jobs SET status = 'running' WHERE id = ?", (job_id,))
        conn.commit()

        if image_type == "card":
            # Re-fetch card images and enqueue only missing ones
            client = CivitaiClient(api_key=api_key)
            try:
                model_data = client.get_model(civitai_model_id)
            except Exception as e:
                print(f"    {_red(f'CivitAI error: {e}')}")
                conn.execute("UPDATE gallery_jobs SET status = 'interrupted' WHERE id = ?", (job_id,))
                conn.commit()
                continue

            from v2.app.civitai_client import extract_cdn_id_from_url, build_cdn_url
            enqueued = 0
            for version in model_data.get("modelVersions", []):
                for img in client.extract_card_images(version):
                    cdn_id = img.get("cdn_id", "")
                    if not cdn_id:
                        continue
                    # Dedup: check if already in media store by origin
                    from v2.app import media_store
                    existing = media_store.get_by_origin("civitai", cdn_id)
                    if existing:
                        continue
                    media_type = img.get("type", "image")
                    url = build_cdn_url(cdn_id, media_type)
                    ext = ".mp4" if media_type == "video" else ".jpeg"
                    from v2.app import download_scheduler
                    download_scheduler.enqueue(
                        url=url,
                        callback="gallery_deliver",
                        callback_args={
                            "origin": "civitai", "origin_id": cdn_id,
                            "origin_url": url, "original_name": f"{cdn_id}{ext}",
                            "model_id": model_id, "version_id": None,
                            "image_type": "card", "civitai_image_id": None,
                            "fetch_generation_data": False, "civitai_api_key": api_key,
                            "gallery_job_id": job_id,
                            "post_id": None, "post_title": None, "username": None, "stats": {},
                        },
                    )
                    enqueued += 1
            print(f"    Enqueued {enqueued} missing card images.")

        elif image_type == "community" and version_id:
            version_source = cat.get_by_source_entity("version", version_id)
            if not version_source:
                print(_red(f"    No CivitAI source for version. Skipping."))
                conn.execute("UPDATE gallery_jobs SET status = 'interrupted' WHERE id = ?", (job_id,))
                conn.commit()
                continue
            civitai_vid = int(version_source["source_id"])

            client = CivitaiClient(api_key=api_key)
            max_images = filters.get("max_images", 200)
            enqueued = 0

            for item in client.iter_images_trpc(
                version_id=civitai_vid,
                sort=filters.get("sort", "Most Reactions"),
                period=filters.get("period", "AllTime"),
                types=filters.get("types"),
                with_meta=filters.get("with_meta", False),
                from_platform=filters.get("from_platform", False),
                limit=min(max_images, 200),
            ):
                normalized = client.normalize_trpc_image(item)
                image_id = normalized.get("id")
                cdn_id = normalized.get("cdn_id", "")
                origin_key = str(image_id) if image_id else cdn_id

                # Dedup
                from v2.app import media_store
                existing = media_store.get_by_origin("civitai", origin_key)
                if existing:
                    continue

                media_type = normalized.get("type", "image")
                url = normalized.get("full_url") or build_cdn_url(cdn_id, media_type)
                ext = ".mp4" if media_type == "video" else ".jpeg"
                stats_data = normalized.get("stats", {})

                from v2.app import download_scheduler
                download_scheduler.enqueue(
                    url=url,
                    callback="gallery_deliver",
                    callback_args={
                        "origin": "civitai",
                        "origin_id": origin_key,
                        "origin_url": url,
                        "original_name": f"{image_id or cdn_id}{ext}",
                        "model_id": model_id, "version_id": version_id,
                        "image_type": "community",
                        "civitai_image_id": image_id,
                        "fetch_generation_data": filters.get("fetch_generation_data", True),
                        "civitai_api_key": api_key,
                        "gallery_job_id": job_id,
                        "post_id": normalized.get("postId"),
                        "post_title": normalized.get("postTitle"),
                        "username": normalized.get("username"),
                        "stats": {
                            "reactions": (stats_data.get("heartCount", 0) or 0) + (stats_data.get("likeCount", 0) or 0),
                            "comments": stats_data.get("commentCount", 0) or 0,
                            "collected": stats_data.get("collectedCount", 0) or 0,
                        },
                        "civitai_url": f"https://civitai.com/images/{image_id}" if image_id else None,
                    },
                )
                enqueued += 1
                if enqueued + completed >= total:
                    break

            print(f"    Enqueued {enqueued} missing community images.")

        job_ids.append(job_id)

    if not job_ids:
        print(_dim("\n  Nothing resumed."))
        return

    if args.background or args.all:
        print(f"\n  {_green(f'{len(job_ids)} job(s) resumed.')}")
        print(f"  Monitor: studio gallery jobs")
        return

    # Live monitor
    print(f"\n  {_bold(f'Monitoring {len(job_ids)} job(s)...')}  (Ctrl+C to detach)\n")
    try:
        while True:
            all_done = True
            for jid in job_ids:
                j = g.get_job_status(jid)
                if j is None:
                    print(f"\r  {_green('✓')} {jid[:12]}... completed                     ")
                    continue
                all_done = False
                total = j["total"] or 0
                completed = j["completed"]
                failed = j["failed"]
                pct = (completed / total * 100) if total > 0 else 0
                bar_w = 30
                filled = int(bar_w * pct / 100)
                bar = "█" * filled + "░" * (bar_w - filled)
                fail_str = f"  {_red(f'{failed} failed')}" if failed else ""
                print(f"\r  [{bar}] {completed}/{total} {pct:.0f}%{fail_str}    ", end="", flush=True)
            if all_done:
                print(f"\n\n  {_green('All done.')}")
                break
            import time as _time
            _time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n  Detached. Jobs continue in background.")
    print()


# ── HTTP commands ────────────────────────────────────────────────────────────

def cmd_http_stats(args):
    """Show HTTP client statistics."""
    from v2.app.http_client import http
    s = http.get_stats()
    if args.json:
        print(json.dumps({
            "total_calls": s.total_calls,
            "total_errors": s.total_errors,
            "total_bytes": s.total_bytes,
            "avg_duration_ms": round(s.avg_duration_ms, 1),
            "calls_by_caller": s.calls_by_caller,
            "errors_by_caller": s.errors_by_caller,
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


def cmd_http_log(args):
    """Show recent HTTP calls."""
    from v2.app.http_client import http
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


# ── DB commands ──────────────────────────────────────────────────────────────

def cmd_db_tables(args):
    """List all tables with row counts."""
    _init()
    from v2.app.db import table_list, table_count
    tables = table_list()
    if args.json:
        print(json.dumps({t: table_count(t) for t in tables}, indent=2))
        return
    print(f"\n  {_bold(f'Tables ({len(tables)})')}\n")
    for t in tables:
        count = table_count(t)
        print(f"  {t:30s} {count:>8d} rows")
    print()


def cmd_db_integrity(args):
    """Run SQLite integrity check."""
    _init()
    from v2.app.db import integrity_check
    result = integrity_check()
    if result == "ok":
        print(f"  {_green('Database integrity OK')}")
    else:
        print(f"  {_red(f'Integrity issue: {result}')}")


def cmd_db_size(args):
    """Show database file size."""
    _init()
    from v2.app.db import db_size_bytes
    size = db_size_bytes()
    if args.json:
        print(json.dumps({"bytes": size}))
        return
    print(f"  Database size: {_fmt_bytes(size)}")


# ── Store commands ───────────────────────────────────────────────────────────

def cmd_store_stats(args):
    """Show model store statistics."""
    from v2.app import model_store as ms
    if args.json:
        print(json.dumps({"count": ms.count(), "total_bytes": ms.total_size()}, indent=2))
        return
    print(f"\n  {_bold('Model Store')}\n")
    print(f"  Files:      {ms.count()}")
    print(f"  Total size: {_fmt_bytes(ms.total_size())}")
    print()


def cmd_store_list(args):
    """List files in model store."""
    from v2.app.db import get_conn
    conn = get_conn()
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


# ── Config commands ──────────────────────────────────────────────────────────

def cmd_config_list(args):
    """List all settings with resolved values."""
    from v2.app.settings import (
        WORKSPACE, STUDIO_DIR, V2_DIR, COMFYUI_DIR, DB_PATH,
        MEDIA_STORE_DIR, MODEL_STORE_DIR, DOWNLOADS_DIR,
        COMFYUI_PORT, COMFYUI_URL, STUDIO_PORT,
        RUNTIME_VERSION, DEV_MODE, REPO_URL, REPO_BRANCH,
        API_KEY, CIVITAI_API_KEY, HF_TOKEN, MAX_CONCURRENT_DOWNLOADS,
        LLAMA_SERVER_PATH, LLAMA_SERVER_PORT,
    )
    items = [
        ("WORKSPACE", str(WORKSPACE)),
        ("STUDIO_DIR", str(STUDIO_DIR)),
        ("V2_DIR", str(V2_DIR)),
        ("COMFYUI_DIR", str(COMFYUI_DIR)),
        ("DB_PATH", str(DB_PATH)),
        ("MEDIA_STORE_DIR", str(MEDIA_STORE_DIR)),
        ("MODEL_STORE_DIR", str(MODEL_STORE_DIR)),
        ("DOWNLOADS_DIR", str(DOWNLOADS_DIR)),
        ("COMFYUI_PORT", COMFYUI_PORT),
        ("COMFYUI_URL", COMFYUI_URL),
        ("STUDIO_PORT", STUDIO_PORT),
        ("RUNTIME_VERSION", str(RUNTIME_VERSION)),
        ("DEV_MODE", str(DEV_MODE)),
        ("REPO_URL", REPO_URL),
        ("REPO_BRANCH", REPO_BRANCH),
        ("API_KEY", API_KEY[:3] + "***" if API_KEY else "-"),
        ("CIVITAI_API_KEY", CIVITAI_API_KEY[:6] + "***" if CIVITAI_API_KEY else "-"),
        ("HF_TOKEN", HF_TOKEN[:6] + "***" if HF_TOKEN else "-"),
        ("MAX_CONCURRENT_DOWNLOADS", str(MAX_CONCURRENT_DOWNLOADS)),
        ("LLAMA_SERVER_PATH", str(LLAMA_SERVER_PATH)),
        ("LLAMA_SERVER_PORT", str(LLAMA_SERVER_PORT)),
    ]
    if args.json:
        print(json.dumps(dict(items), indent=2))
        return
    print(f"\n  {_bold('Settings')}\n")
    for k, v in items:
        print(f"  {k:30s} {v}")
    print()


def cmd_config_get(args):
    """Get a single setting value."""
    import v2.app.settings as s
    val = getattr(s, args.key, None)
    if val is None:
        print(_red(f"  Unknown setting: {args.key}"))
        sys.exit(1)
    print(val)


def cmd_config_set(args):
    """Set a setting (placeholder — writes to env only, not DB yet)."""
    print(_yellow("  config set is not implemented yet (needs DB settings table)."))
    print(f"  Would set: {args.key} = {args.value}")


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

            Files are stored in a sharded flat directory (V2_DIR/media/)
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

    # ── catalog ──

    cat_parser = subparsers.add_parser("catalog", help="Model catalog operations",
        description="Manage the model catalog: parents, versions, files, CivitAI import.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    cat_sub = cat_parser.add_subparsers(dest="subcommand", title="subcommands")

    p = cat_sub.add_parser("stats", help="Catalog statistics", parents=[common])
    p.set_defaults(func=cmd_catalog_stats)

    p = cat_sub.add_parser("list", help="List models", parents=[common])
    p.add_argument("--search", "-s", help="Search by name")
    p.add_argument("--category", help="Filter by category")
    p.add_argument("--type", help="Filter by CivitAI type")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--offset", type=int, default=0)
    p.set_defaults(func=cmd_catalog_list)

    p = cat_sub.add_parser("info", help="Model detail", parents=[common])
    p.add_argument("id", help="Model ID")
    p.set_defaults(func=cmd_catalog_info)

    p = cat_sub.add_parser("import", help="Import from CivitAI (upsert)", parents=[common])
    p.add_argument("civitai_id", type=int, help="CivitAI model ID")
    p.add_argument("--versions", help="Comma-separated CivitAI version IDs (default: all)")
    p.add_argument("--category", help="Override category")
    p.add_argument("--api-key", help="CivitAI API key (default: from settings)")
    p.set_defaults(func=cmd_catalog_import)

    p = cat_sub.add_parser("versions", help="List versions of a model", parents=[common])
    p.add_argument("model_id", help="Model ID")
    p.set_defaults(func=cmd_catalog_versions)

    p = cat_sub.add_parser("files", help="List files of a version", parents=[common])
    p.add_argument("version_id", help="Version ID")
    p.set_defaults(func=cmd_catalog_files)

    # ── download ──

    dl_parser = subparsers.add_parser("download", help="Download queue operations",
        description="Manage the download scheduler: queue, cancel, retry, cleanup.")
    dl_sub = dl_parser.add_subparsers(dest="subcommand", title="subcommands")

    p = dl_sub.add_parser("list", help="List downloads", parents=[common])
    p.add_argument("--active", action="store_true", help="Only active (queued + downloading)")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_download_list)

    p = dl_sub.add_parser("status", help="Download detail", parents=[common])
    p.add_argument("id", help="Download ID")
    p.set_defaults(func=cmd_download_status)

    p = dl_sub.add_parser("cancel", help="Cancel a download", parents=[common])
    p.add_argument("id", help="Download ID")
    p.set_defaults(func=cmd_download_cancel)

    p = dl_sub.add_parser("retry", help="Retry a failed download", parents=[common])
    p.add_argument("id", help="Download ID")
    p.set_defaults(func=cmd_download_retry)

    p = dl_sub.add_parser("cleanup", help="Remove temp files", parents=[common])
    p.set_defaults(func=cmd_download_cleanup)

    p = dl_sub.add_parser("queue", help="Queue statistics", parents=[common])
    p.set_defaults(func=cmd_download_queue)

    # ── gallery ──

    gal_parser = subparsers.add_parser("gallery", help="Gallery operations",
        description="Download, monitor, and inspect gallery images for cataloged models.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    gal_sub = gal_parser.add_subparsers(dest="subcommand", title="subcommands")

    p = gal_sub.add_parser("stats", help="Total gallery statistics", parents=[common],
        description="Aggregate counts and sizes for card and community images.")
    p.set_defaults(func=cmd_gallery_stats)

    p = gal_sub.add_parser("status", help="Gallery status per model/version", parents=[common],
        description="Show which models/versions have gallery images and how many.")
    p.add_argument("model_id", nargs="?", help="Model ID (optional, shows all if omitted)")
    p.add_argument("--vers-id", help="Version ID (with model_id)", dest="version")
    p.add_argument("--empty", action="store_true", help="Show only models/versions without gallery")
    p.set_defaults(func=cmd_gallery_status)

    p = gal_sub.add_parser("download", help="Download gallery images", parents=[common],
        description=dedent("""\
            Download gallery images for a cataloged model.
            Interactive if no model_id given. Shows live progress by default.
            Ctrl+C detaches without stopping the job.
        """),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("model_id", nargs="?", help="Model ID (interactive if omitted)")
    p.add_argument("--all", action="store_true", help="Card + community all versions, no prompt")
    p.add_argument("--cards", action="store_true", help="Only card images")
    p.add_argument("--vers-id", help="Download community for this specific version", dest="version")
    p.add_argument("--background", action="store_true", help="Enqueue and exit (no live monitor)")
    p.set_defaults(func=cmd_gallery_download)

    p = gal_sub.add_parser("jobs", help="List active gallery jobs (snapshot)", parents=[common])
    p.set_defaults(func=cmd_gallery_jobs)

    p = gal_sub.add_parser("job", help="Monitor a gallery job (live)", parents=[common],
        description="Live progress monitor. Ctrl+C exits without stopping. --json for snapshot.")
    p.add_argument("id", help="Job ID")
    p.set_defaults(func=cmd_gallery_job)

    p = gal_sub.add_parser("stop", help="Stop a running gallery job", parents=[common])
    p.add_argument("id", help="Job ID")
    p.set_defaults(func=cmd_gallery_stop)

    p = gal_sub.add_parser("cleanup", help="Remove interrupted/failed jobs", parents=[common],
        description="Shows a report of interrupted/failed jobs, then deletes them.")
    p.add_argument("--force", "-f", action="store_true", help="Skip confirmation")
    p.set_defaults(func=cmd_gallery_cleanup)

    p = gal_sub.add_parser("resume", help="Resume interrupted gallery jobs", parents=[common],
        description=dedent("""\
            Re-fetches from CivitAI and enqueues only missing images.
            Dedup ensures nothing is downloaded twice.
            Interactive if no job_id given.
        """),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("job_id", nargs="?", help="Job ID to resume (interactive if omitted)")
    p.add_argument("--all", action="store_true", help="Resume all interrupted jobs")
    p.add_argument("--background", action="store_true", help="Don't show live monitor")
    p.set_defaults(func=cmd_gallery_resume)

    # ── http ──

    http_parser = subparsers.add_parser("http", help="HTTP client stats and log",
        description="Monitor outgoing HTTP API calls.")
    http_sub = http_parser.add_subparsers(dest="subcommand", title="subcommands")

    p = http_sub.add_parser("stats", help="HTTP call statistics", parents=[common])
    p.set_defaults(func=cmd_http_stats)

    p = http_sub.add_parser("log", help="Recent HTTP calls", parents=[common])
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--caller", help="Filter by caller name")
    p.set_defaults(func=cmd_http_log)

    # ── db ──

    db_parser = subparsers.add_parser("db", help="Database operations",
        description="Database inspection and maintenance.")
    db_sub = db_parser.add_subparsers(dest="subcommand", title="subcommands")

    p = db_sub.add_parser("tables", help="List tables with row counts", parents=[common])
    p.set_defaults(func=cmd_db_tables)

    p = db_sub.add_parser("integrity", help="Run integrity check", parents=[common])
    p.set_defaults(func=cmd_db_integrity)

    p = db_sub.add_parser("size", help="Database file size", parents=[common])
    p.set_defaults(func=cmd_db_size)

    # ── store ──

    store_parser = subparsers.add_parser("store", help="Model store operations",
        description="Physical model file storage.")
    store_sub = store_parser.add_subparsers(dest="subcommand", title="subcommands")

    p = store_sub.add_parser("stats", help="Store statistics", parents=[common])
    p.set_defaults(func=cmd_store_stats)

    p = store_sub.add_parser("list", help="List stored files", parents=[common])
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_store_list)

    # ── config ──

    cfg_parser = subparsers.add_parser("config", help="Settings",
        description="View and manage application settings.")
    cfg_sub = cfg_parser.add_subparsers(dest="subcommand", title="subcommands")

    p = cfg_sub.add_parser("list", help="List all settings", parents=[common])
    p.set_defaults(func=cmd_config_list)

    p = cfg_sub.add_parser("get", help="Get a setting", parents=[common])
    p.add_argument("key", help="Setting name (e.g. API_KEY)")
    p.set_defaults(func=cmd_config_get)

    p = cfg_sub.add_parser("set", help="Set a setting", parents=[common])
    p.add_argument("key", help="Setting name")
    p.add_argument("value", help="New value")
    p.set_defaults(func=cmd_config_set)

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
