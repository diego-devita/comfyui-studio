"""CLI commands: studio gallery (delegates to _legacy)."""
from textwrap import dedent
from v2.app.cli._legacy import (
    cmd_gallery_stats, cmd_gallery_status, cmd_gallery_download,
    cmd_gallery_jobs, cmd_gallery_job, cmd_gallery_stop,
    cmd_gallery_cleanup, cmd_gallery_resume,
)
import argparse

def register(subparsers, common):
    p = subparsers.add_parser("gallery", help="Gallery operations",
        description="Download, monitor, and inspect gallery images.", formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="subcommand", title="subcommands")
    sub.add_parser("stats", help="Total gallery statistics", parents=[common]).set_defaults(func=cmd_gallery_stats)
    s = sub.add_parser("status", help="Gallery status per model", parents=[common])
    s.add_argument("model_id", nargs="?"); s.add_argument("--vers-id", dest="version"); s.add_argument("--empty", action="store_true")
    s.set_defaults(func=cmd_gallery_status)
    s = sub.add_parser("download", help="Download gallery images", parents=[common],
        description=dedent("Download gallery images. Interactive if no model_id. Ctrl+C detaches."),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    s.add_argument("model_id", nargs="?"); s.add_argument("--all", action="store_true"); s.add_argument("--cards", action="store_true")
    s.add_argument("--vers-id", dest="version"); s.add_argument("--background", action="store_true")
    s.set_defaults(func=cmd_gallery_download)
    sub.add_parser("jobs", help="Active gallery jobs", parents=[common]).set_defaults(func=cmd_gallery_jobs)
    s = sub.add_parser("job", help="Monitor job (live)", parents=[common]); s.add_argument("id"); s.set_defaults(func=cmd_gallery_job)
    s = sub.add_parser("stop", help="Stop a job", parents=[common]); s.add_argument("id"); s.set_defaults(func=cmd_gallery_stop)
    s = sub.add_parser("cleanup", help="Remove failed jobs", parents=[common]); s.add_argument("--force", "-f", action="store_true"); s.set_defaults(func=cmd_gallery_cleanup)
    s = sub.add_parser("resume", help="Resume interrupted", parents=[common],
        description=dedent("Re-fetch from CivitAI, enqueue only missing. Dedup."), formatter_class=argparse.RawDescriptionHelpFormatter)
    s.add_argument("job_id", nargs="?"); s.add_argument("--all", action="store_true"); s.add_argument("--background", action="store_true")
    s.set_defaults(func=cmd_gallery_resume)
