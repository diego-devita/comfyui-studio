"""CLI commands: studio config — settings."""

import json
import sys
from v2.app.cli._common import _bold, _yellow, _red


def cmd_list(args):
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


def cmd_get(args):
    import v2.app.settings as s
    val = getattr(s, args.key, None)
    if val is None:
        print(_red(f"  Unknown setting: {args.key}"))
        sys.exit(1)
    print(val)


def cmd_set(args):
    print(_yellow("  config set is not implemented yet (needs DB settings table)."))
    print(f"  Would set: {args.key} = {args.value}")


def register(subparsers, common):
    p = subparsers.add_parser("config", help="Settings",
        description="View and manage application settings.")
    sub = p.add_subparsers(dest="subcommand", title="subcommands")

    s = sub.add_parser("list", help="List all settings", parents=[common])
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("get", help="Get a setting", parents=[common])
    s.add_argument("key", help="Setting name (e.g. API_KEY)")
    s.set_defaults(func=cmd_get)

    s = sub.add_parser("set", help="Set a setting", parents=[common])
    s.add_argument("key", help="Setting name")
    s.add_argument("value", help="New value")
    s.set_defaults(func=cmd_set)
