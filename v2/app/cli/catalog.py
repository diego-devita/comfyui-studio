"""CLI commands: studio catalog (delegates to _legacy)."""
from v2.app.cli._legacy import cmd_catalog_stats, cmd_catalog_list, cmd_catalog_info, cmd_catalog_import, cmd_catalog_versions, cmd_catalog_files

def register(subparsers, common):
    p = subparsers.add_parser("catalog", help="Model catalog operations")
    sub = p.add_subparsers(dest="subcommand", title="subcommands")
    sub.add_parser("stats", help="Catalog statistics", parents=[common]).set_defaults(func=cmd_catalog_stats)
    s = sub.add_parser("list", help="List models", parents=[common])
    s.add_argument("--search", "-s"); s.add_argument("--category"); s.add_argument("--type")
    s.add_argument("--limit", type=int, default=50); s.add_argument("--offset", type=int, default=0)
    s.set_defaults(func=cmd_catalog_list)
    s = sub.add_parser("info", help="Model detail", parents=[common]); s.add_argument("id"); s.set_defaults(func=cmd_catalog_info)
    s = sub.add_parser("import", help="Import from CivitAI", parents=[common]); s.add_argument("civitai_id", type=int)
    s.add_argument("--versions"); s.add_argument("--category"); s.add_argument("--api-key"); s.set_defaults(func=cmd_catalog_import)
    s = sub.add_parser("versions", help="List versions", parents=[common]); s.add_argument("model_id"); s.set_defaults(func=cmd_catalog_versions)
    s = sub.add_parser("files", help="List files", parents=[common]); s.add_argument("version_id"); s.set_defaults(func=cmd_catalog_files)
