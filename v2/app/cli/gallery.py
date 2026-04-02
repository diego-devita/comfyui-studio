"""CLI commands: studio gallery — gallery operations."""

import argparse
import json
import sys
import time as _time
from textwrap import dedent

from v2.app.cli._common import (
    _init, _db_conn, _bold, _green, _red, _yellow, _cyan, _dim,
    _fmt_bytes, _fmt_date, _table,
)


def _get_gal():
    _init()
    from v2.app.domain import gallery
    return gallery

def _get_cat():
    _init()
    from v2.app.domain import catalog
    return catalog


def cmd_gallery_stats(args):
    """Show total gallery statistics (card + community counts and sizes)."""
    g = _get_gal()
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
    g = _get_gal()
    cat = _get_cat()
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
    g = _get_gal()
    cat = _get_cat()
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
    g = _get_gal()
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
    g = _get_gal()
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
    g = _get_gal()
    g.stop_job(args.id)
    print(f"  {_green('Stop signal sent')} for {args.id[:12]}...")


def cmd_gallery_cleanup(args):
    """Clean up interrupted/failed gallery jobs with a report."""
    g = _get_gal()
    cat = _get_cat()
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
    g = _get_gal()
    cat = _get_cat()
    from v2.app.settings import CIVITAI_API_KEY
    from v2.app.clients.civitai import CivitaiClient
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

            from v2.app.clients.civitai import extract_cdn_id_from_url, build_cdn_url
            enqueued = 0
            for version in model_data.get("modelVersions", []):
                for img in client.extract_card_images(version):
                    cdn_id = img.get("cdn_id", "")
                    if not cdn_id:
                        continue
                    # Dedup: check if already in media store by origin
                    from v2.app.stores import media as media_store
                    existing = media_store.get_by_origin("civitai", cdn_id)
                    if existing:
                        continue
                    media_type = img.get("type", "image")
                    url = build_cdn_url(cdn_id, media_type)
                    ext = ".mp4" if media_type == "video" else ".jpeg"
                    from v2.app.domain import download as download_scheduler
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
                from v2.app.stores import media as media_store
                existing = media_store.get_by_origin("civitai", origin_key)
                if existing:
                    continue

                media_type = normalized.get("type", "image")
                url = normalized.get("full_url") or build_cdn_url(cdn_id, media_type)
                ext = ".mp4" if media_type == "video" else ".jpeg"
                stats_data = normalized.get("stats", {})

                from v2.app.domain import download as download_scheduler
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



def register(subparsers, common):
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
    
    
