"""CLI commands: studio gallery — gallery operations."""

import argparse
import json
import sys
import time as _time
from textwrap import dedent

from v2.app.cli._common import (
    _init, _bold, _green, _red, _yellow, _cyan, _dim,
    _fmt_bytes, _fmt_date, _table,
)


def _gal():
    _init()
    from v2.app.domain import gallery
    return gallery

def _cat():
    _init()
    from v2.app.domain import catalog
    return catalog


def cmd_stats(args):
    s = _gal().get_gallery_stats()
    if args.json:
        print(json.dumps(s, indent=2)); return
    print(f"\n  {_bold('Gallery Statistics')}\n")
    print(f"  Card images:      {s['card_count']:>6d}  ({_fmt_bytes(s['card_bytes'])})")
    print(f"  Community images: {s['community_count']:>6d}  ({_fmt_bytes(s['community_bytes'])})")
    print(f"  Total:            {s['total_count']:>6d}  ({_fmt_bytes(s['total_bytes'])})")
    print()


def cmd_status(args):
    g, cat = _gal(), _cat()
    if args.model_id:
        m = cat.get_model(args.model_id)
        if not m: print(_red(f"  Model not found: {args.model_id}")); sys.exit(1)
        gal = g.get_model_gallery(m["id"])
        if args.version:
            v_count = gal["versions"].get(args.version, {})
            if args.json: print(json.dumps({"model_id": m["id"], "version_id": args.version, **v_count}, indent=2)); return
            print(f"\n  {m['name']} / version {args.version[:12]}...")
            print(f"  Community: {v_count.get('count', 0)} images ({_fmt_bytes(v_count.get('bytes', 0))})\n"); return
        if args.json: print(json.dumps({"model_id": m["id"], "name": m["name"], **gal}, indent=2, default=str)); return
        print(f"\n  {_bold(m['name'])}\n")
        print(f"  Card images: {gal['card_count']} ({_fmt_bytes(gal['card_bytes'])})")
        for v in cat.get_versions_by_model(m["id"]):
            vc = gal["versions"].get(v["id"], {})
            print(f"    {v['name']:35s}  {vc.get('count', 0):>5d} community  ({_fmt_bytes(vc.get('bytes', 0))})")
        print(); return
    models = cat.find_models(limit=500)
    rows = []
    for m in models:
        gal = g.get_model_gallery(m["id"])
        cc, mc = gal["card_count"], gal["community_count"]
        if args.empty and (cc > 0 or mc > 0): continue
        rows.append({"name": m["name"], "card": cc, "community": mc,
                     "card_bytes": gal["card_bytes"], "community_bytes": gal["community_bytes"]})
    if args.json: print(json.dumps(rows, indent=2)); return
    if not rows: print(_dim("  No models match.")); return
    print(f"\n  {_bold('Gallery Status')}\n")
    _table(["Model", "Card", "Community", "Total Size"],
           [[r["name"][:40], str(r["card"]), str(r["community"]),
             _fmt_bytes(r["card_bytes"] + r["community_bytes"])] for r in rows])
    print(f"\n  {len(rows)} models, {sum(r['card'] for r in rows)} card, {sum(r['community'] for r in rows)} community\n")


def cmd_download(args):
    g, cat = _gal(), _cat()
    from v2.app.settings import CIVITAI_API_KEY
    api_key = CIVITAI_API_KEY
    if not api_key: print(_red("  CIVITAI_API_KEY not set.")); sys.exit(1)

    if not args.model_id:
        models = cat.find_models(limit=100)
        if not models: print(_dim("  Catalog empty.")); return
        print(f"\n  {_bold('Choose a model:')}\n")
        for i, m in enumerate(models): print(f"  {i+1:3d}. {m['name'][:50]}")
        try: choice = int(input("\n  Number: ").strip()) - 1
        except: print("  Cancelled."); return
        if choice < 0 or choice >= len(models): print("  Cancelled."); return
        selected = models[choice]
    else:
        selected = cat.get_model(args.model_id)
        if not selected: print(_red(f"  Model not found: {args.model_id}")); sys.exit(1)

    model_id = selected["id"]
    source = cat.get_by_source_entity("model", model_id)
    if not source: print(_red(f"  No CivitAI source for '{selected['name']}'.")); sys.exit(1)
    civitai_model_id = int(source["source_id"])
    job_ids = []

    if args.cards or args.all:
        print(f"\n  Downloading cards for {_cyan(selected['name'])}...")
        jid = g.download_card_images(model_id, civitai_model_id, api_key)
        if jid: job_ids.append(("card", jid))
        else: print(_dim("  No card images."))

    if args.version:
        v = cat.get_version(args.version)
        if not v: print(_red(f"  Version not found.")); sys.exit(1)
        vs = cat.get_by_source_entity("version", args.version)
        if not vs: print(_red("  No CivitAI source.")); sys.exit(1)
        print(f"  Downloading community for {_cyan(v['name'])}...")
        jid = g.download_community_images(model_id, args.version, int(vs["source_id"]), api_key)
        if jid: job_ids.append(("community", jid))
    elif args.all:
        for v in cat.get_versions_by_model(model_id):
            vs = cat.get_by_source_entity("version", v["id"])
            if not vs: continue
            print(f"  Downloading community for {_cyan(v['name'])}...")
            jid = g.download_community_images(model_id, v["id"], int(vs["source_id"]), api_key)
            if jid: job_ids.append(("community", jid))
    elif not args.cards:
        versions = cat.get_versions_by_model(model_id)
        print(f"\n  Model: {_bold(selected['name'])}  ({len(versions)} versions)\n")
        print("  1. Card images only\n  2. Community (choose version)\n  3. Everything\n")
        try: choice = input("  Choice [1/2/3]: ").strip()
        except: print("  Cancelled."); return
        if choice == "1":
            jid = g.download_card_images(model_id, civitai_model_id, api_key)
            if jid: job_ids.append(("card", jid))
        elif choice == "2":
            for i, v in enumerate(versions): print(f"    {i+1}. {v['name']}")
            try: vi = int(input("  Version: ").strip()) - 1
            except: print("  Cancelled."); return
            if 0 <= vi < len(versions):
                v = versions[vi]; vs = cat.get_by_source_entity("version", v["id"])
                if vs:
                    jid = g.download_community_images(model_id, v["id"], int(vs["source_id"]), api_key)
                    if jid: job_ids.append(("community", jid))
        elif choice == "3":
            jid = g.download_card_images(model_id, civitai_model_id, api_key)
            if jid: job_ids.append(("card", jid))
            for v in versions:
                vs = cat.get_by_source_entity("version", v["id"])
                if vs:
                    jid = g.download_community_images(model_id, v["id"], int(vs["source_id"]), api_key)
                    if jid: job_ids.append(("community", jid))

    if not job_ids: print(_dim("\n  Nothing to download.")); return
    if args.background:
        print(f"\n  {_green(f'{len(job_ids)} job(s) started.')}\n  Monitor: studio gallery jobs\n"); return
    _monitor_jobs(_gal(), job_ids)


def cmd_jobs(args):
    jobs = _gal().list_active_jobs()
    if args.json: print(json.dumps(jobs, indent=2, default=str)); return
    if not jobs: print(_dim("  No active gallery jobs.")); return
    print(f"\n  {_bold(f'Gallery Jobs ({len(jobs)})')}\n")
    _table(["ID", "Type", "Status", "Progress", "Failed", "Created"],
           [[j["id"][:12] + "...", j["image_type"], j["status"],
             f"{j['completed']}/{j['total']}", str(j["failed"]),
             _fmt_date(j["created_at"])[:16]] for j in jobs])
    print()


def cmd_job(args):
    g = _gal()
    j = g.get_job_status(args.id)
    if not j: print(_green("  Job completed (or not found).")); return
    if args.json: print(json.dumps(j, indent=2, default=str)); return
    print(f"\n  {_bold('Gallery Job')} {_cyan(j['id'][:12])}...  (Ctrl+C to exit)\n")
    _monitor_single(g, args.id)


def cmd_stop(args):
    _gal().stop_job(args.id)
    print(f"  {_green('Stop signal sent')} for {args.id[:12]}...")


def cmd_cleanup(args):
    g, cat = _gal(), _cat()
    stale = g.list_stale_jobs()
    if not stale: print(_green("  No stale jobs.")); return
    if args.json: print(json.dumps(stale, indent=2, default=str)); return
    print(f"\n  {_bold(f'Stale gallery jobs ({len(stale)})')}\n")
    for r in stale:
        m = cat.get_model(r["model_id"])
        total = r["total"] or 0
        never = max(0, total - r["completed"] - r["failed"])
        print(f"  {r['id'][:12]}...  {r['status']:12s}  {m['name'][:35] if m else '?'}")
        print(f"    {r['image_type']}  {r['completed']}/{total} done, {r['failed']} failed, {never} never started\n")
    if not args.force:
        try:
            if input(f"  Delete {len(stale)} job(s)? [y/N] ").strip().lower() != "y":
                print("  Cancelled."); return
        except: print("\n  Cancelled."); return
    print(f"  {_green(f'{g.delete_stale_jobs()} job(s) cleaned up.')}")


def cmd_resume(args):
    g, cat = _gal(), _cat()
    from v2.app.settings import CIVITAI_API_KEY
    api_key = CIVITAI_API_KEY
    if not api_key: print(_red("  CIVITAI_API_KEY not set.")); sys.exit(1)

    interrupted = [j for j in g.list_stale_jobs() if j["status"] == "interrupted"]

    if args.job_id:
        jobs = [j for j in interrupted if j["id"] == args.job_id]
        if not jobs: print(_red(f"  Not found or not interrupted.")); sys.exit(1)
    elif args.all:
        jobs = interrupted
    else:
        if not interrupted: print(_green("  No interrupted jobs.")); return
        print(f"\n  {_bold('Interrupted jobs:')}\n")
        for i, j in enumerate(interrupted):
            m = cat.get_model(j["model_id"])
            print(f"  {i+1:3d}. {j['id'][:12]}... {m['name'][:40] if m else '?'}  {j['completed']}/{j['total']}")
        try:
            choice = input("\n  Resume which? (number, 'all', Enter=cancel): ").strip()
            if choice.lower() == "all": jobs = interrupted
            elif choice == "": print("  Cancelled."); return
            else:
                idx = int(choice) - 1
                jobs = [interrupted[idx]] if 0 <= idx < len(interrupted) else []
        except: print("\n  Cancelled."); return

    if not jobs: print(_green("  Nothing to resume.")); return

    job_ids = []
    for j in jobs:
        m = cat.get_model(j["model_id"])
        print(f"\n  Resuming {_cyan(m['name'][:40] if m else '?')} ({j['image_type']})...")
        try:
            enqueued = g.resume_job(j["id"], api_key)
            print(f"    Enqueued {enqueued} missing images.")
            job_ids.append(j["id"])
        except Exception as e:
            print(f"    {_red(str(e))}")

    if not job_ids: print(_dim("\n  Nothing resumed.")); return
    if args.background or args.all:
        print(f"\n  {_green(f'{len(job_ids)} job(s) resumed.')}\n"); return
    _monitor_jobs(_gal(), [(None, jid) for jid in job_ids])


# ── Live monitor helpers ─────────────────────────────────────────────────────

def _monitor_jobs(g, job_ids):
    print(f"\n  {_bold(f'Monitoring {len(job_ids)} job(s)...')}  (Ctrl+C to detach)\n")
    try:
        while True:
            all_done = True
            for jtype, jid in job_ids:
                j = g.get_job_status(jid)
                if j is None:
                    print(f"\r  {_green('✓')} {jtype or ''}: completed                     "); continue
                all_done = False
                total = j["total"] or 0
                pct = (j["completed"] / total * 100) if total > 0 else 0
                filled = int(30 * pct / 100)
                bar = "█" * filled + "░" * (30 - filled)
                fail = f"  {_red(str(j['failed']) + ' failed')}" if j["failed"] else ""
                print(f"\r  [{bar}] {j['completed']}/{total} {pct:.0f}% {jtype or ''}{fail}    ", end="", flush=True)
            if all_done: print(f"\n\n  {_green('All done.')}"); break
            _time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n\n  Detached. Jobs continue in background.")
        for _, jid in job_ids: print(f"  Stop: studio gallery stop {jid[:12]}")
    print()


def _monitor_single(g, job_id):
    try:
        while True:
            j = g.get_job_status(job_id)
            if j is None: print(f"\r  {_green('Completed.')}                              "); break
            total = j["total"] or 0
            pct = (j["completed"] / total * 100) if total > 0 else 0
            filled = int(40 * pct / 100)
            bar = "█" * filled + "░" * (40 - filled)
            fail = f"  {_red(str(j['failed']) + ' failed')}" if j["failed"] else ""
            print(f"\r  [{bar}] {j['completed']}/{total} {pct:.0f}%  {j['status']}{fail}    ", end="", flush=True)
            if j["status"] == "error": print(f"\n  {_red('Job failed.')}"); break
            _time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n  Exited. Job continues.")
    print()


# ── Parser registration ──────────────────────────────────────────────────────

def register(subparsers, common):
    p = subparsers.add_parser("gallery", help="Gallery operations",
        description="Download, monitor, and inspect gallery images.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="subcommand", title="subcommands")

    sub.add_parser("stats", help="Total gallery statistics", parents=[common]).set_defaults(func=cmd_stats)

    s = sub.add_parser("status", help="Gallery status per model", parents=[common])
    s.add_argument("model_id", nargs="?"); s.add_argument("--vers-id", dest="version")
    s.add_argument("--empty", action="store_true"); s.set_defaults(func=cmd_status)

    s = sub.add_parser("download", help="Download gallery images", parents=[common])
    s.add_argument("model_id", nargs="?"); s.add_argument("--all", action="store_true")
    s.add_argument("--cards", action="store_true"); s.add_argument("--vers-id", dest="version")
    s.add_argument("--background", action="store_true"); s.set_defaults(func=cmd_download)

    sub.add_parser("jobs", help="Active gallery jobs", parents=[common]).set_defaults(func=cmd_jobs)

    s = sub.add_parser("job", help="Monitor job (live)", parents=[common])
    s.add_argument("id"); s.set_defaults(func=cmd_job)

    s = sub.add_parser("stop", help="Stop a job", parents=[common])
    s.add_argument("id"); s.set_defaults(func=cmd_stop)

    s = sub.add_parser("cleanup", help="Remove failed/interrupted jobs", parents=[common])
    s.add_argument("--force", "-f", action="store_true"); s.set_defaults(func=cmd_cleanup)

    s = sub.add_parser("resume", help="Resume interrupted jobs", parents=[common])
    s.add_argument("job_id", nargs="?"); s.add_argument("--all", action="store_true")
    s.add_argument("--background", action="store_true"); s.set_defaults(func=cmd_resume)
