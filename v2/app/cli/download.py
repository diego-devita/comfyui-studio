"""CLI commands: studio download (delegates to _legacy)."""
from v2.app.cli._legacy import cmd_download_list, cmd_download_status, cmd_download_cancel, cmd_download_retry, cmd_download_cleanup, cmd_download_queue

def register(subparsers, common):
    p = subparsers.add_parser("download", help="Download queue operations")
    sub = p.add_subparsers(dest="subcommand", title="subcommands")
    s = sub.add_parser("list", help="List downloads", parents=[common])
    s.add_argument("--active", action="store_true"); s.add_argument("--limit", type=int, default=50); s.set_defaults(func=cmd_download_list)
    s = sub.add_parser("status", help="Download detail", parents=[common]); s.add_argument("id"); s.set_defaults(func=cmd_download_status)
    s = sub.add_parser("cancel", help="Cancel", parents=[common]); s.add_argument("id"); s.set_defaults(func=cmd_download_cancel)
    s = sub.add_parser("retry", help="Retry", parents=[common]); s.add_argument("id"); s.set_defaults(func=cmd_download_retry)
    sub.add_parser("cleanup", help="Remove temp files", parents=[common]).set_defaults(func=cmd_download_cleanup)
    sub.add_parser("queue", help="Queue stats", parents=[common]).set_defaults(func=cmd_download_queue)
