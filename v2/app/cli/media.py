"""CLI commands: studio media (delegates to _legacy)."""
from v2.app.cli._legacy import (
    cmd_media_stats, cmd_media_list, cmd_media_info, cmd_media_find,
    cmd_media_doctor, cmd_media_reindex, cmd_media_import, cmd_media_export,
    cmd_media_delete, cmd_media_verify, cmd_media_dedup, cmd_media_exif,
    cmd_media_thumb,
)

def register(subparsers, common):
    from v2.app.cli._legacy import build_parser as _bp
    # Extract just the media parser section by building the full parser
    # and copying its media subparser. This is a workaround until we
    # fully split the CLI.
    import argparse
    from textwrap import dedent
    p = subparsers.add_parser("media", help="Media store operations",
        description="Manage the centralised media file store.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="subcommand", title="subcommands")
    sub.add_parser("stats", help="Show store statistics", parents=[common]).set_defaults(func=cmd_media_stats)
    s = sub.add_parser("list", help="List media files", parents=[common])
    s.add_argument("--type", choices=["image", "video"]); s.add_argument("--origin"); s.add_argument("--format")
    s.add_argument("--search", "-s"); s.add_argument("--sort", default="created_at"); s.add_argument("--desc", action="store_true")
    s.add_argument("--limit", type=int, default=50); s.add_argument("--offset", type=int, default=0)
    s.set_defaults(func=cmd_media_list)
    s = sub.add_parser("info", help="Media detail", parents=[common]); s.add_argument("id"); s.set_defaults(func=cmd_media_info)
    s = sub.add_parser("find", help="Search media", parents=[common])
    s.add_argument("--hash"); s.add_argument("--origin"); s.add_argument("--origin-id"); s.add_argument("--name")
    s.set_defaults(func=cmd_media_find)
    s = sub.add_parser("doctor", help="Check consistency", parents=[common])
    s.add_argument("--fix", action="store_true"); s.add_argument("--verify-hashes", action="store_true")
    s.set_defaults(func=cmd_media_doctor)
    s = sub.add_parser("reindex", help="Reprocess metadata/thumbs", parents=[common])
    s.add_argument("--force", action="store_true"); s.add_argument("--thumbs-only", action="store_true")
    s.add_argument("--exif-only", action="store_true"); s.add_argument("--properties-only", action="store_true")
    s.set_defaults(func=cmd_media_reindex)
    s = sub.add_parser("import", help="Import files", parents=[common])
    s.add_argument("path"); s.add_argument("--origin", default="upload"); s.add_argument("--origin-id")
    s.add_argument("--recursive", "-r", action="store_true"); s.set_defaults(func=cmd_media_import)
    s = sub.add_parser("export", help="Export file", parents=[common])
    s.add_argument("id"); s.add_argument("dest"); s.add_argument("--with-thumbs", action="store_true")
    s.set_defaults(func=cmd_media_export)
    s = sub.add_parser("delete", help="Delete media", parents=[common])
    s.add_argument("ids", nargs="+"); s.add_argument("--force", "-f", action="store_true"); s.set_defaults(func=cmd_media_delete)
    s = sub.add_parser("verify", help="Verify hashes", parents=[common])
    s.add_argument("--id"); s.add_argument("--all", action="store_true"); s.set_defaults(func=cmd_media_verify)
    s = sub.add_parser("dedup", help="Find duplicates", parents=[common])
    s.add_argument("--dry-run", action="store_true"); s.set_defaults(func=cmd_media_dedup)
    s = sub.add_parser("exif", help="Show EXIF", parents=[common]); s.add_argument("id"); s.add_argument("--raw", action="store_true"); s.set_defaults(func=cmd_media_exif)
    s = sub.add_parser("thumb", help="Show/regen thumbs", parents=[common]); s.add_argument("id")
    s.add_argument("--regenerate", action="store_true"); s.add_argument("--size", choices=["xs","sm","md"]); s.set_defaults(func=cmd_media_thumb)
