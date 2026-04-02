"""CLI entry point — builds parser, dispatches to subcommand modules."""

import argparse
import sys

from v2.app.cli._common import _init


def build_parser() -> argparse.ArgumentParser:
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

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="Output in JSON format")
    common.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    from v2.app.cli import media, catalog, gallery, download, http, db, store, config
    media.register(subparsers, common)
    catalog.register(subparsers, common)
    gallery.register(subparsers, common)
    download.register(subparsers, common)
    http.register(subparsers, common)
    db.register(subparsers, common)
    store.register(subparsers, common)
    config.register(subparsers, common)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not hasattr(args, "json"):
        args.json = False
    if not hasattr(args, "verbose"):
        args.verbose = False

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if hasattr(args, "subcommand") and not args.subcommand:
        parser.parse_args([args.command, "--help"])
        sys.exit(0)

    if hasattr(args, "func"):
        try:
            _init()
            args.func(args)
        except KeyboardInterrupt:
            print("\n  Interrupted.")
            sys.exit(130)
        except Exception as e:
            from v2.app.cli._common import _red
            print(f"\n  {_red(f'Error: {e}')}")
            if args.verbose:
                import traceback
                traceback.print_exc()
            sys.exit(1)
    else:
        parser.print_help()
