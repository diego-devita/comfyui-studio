"""CLI common helpers — output formatting, colors, tables."""

import json
import sys

# ANSI color codes (disabled when piped)
_USE_COLOR = sys.stdout.isatty()

def _c(code: str, text: str) -> str:
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
    if b < 1024:
        return f"{b} B"
    if b < 1024 * 1024:
        return f"{b / 1024:.1f} KB"
    if b < 1024 * 1024 * 1024:
        return f"{b / (1024 * 1024):.1f} MB"
    return f"{b / (1024 * 1024 * 1024):.2f} GB"


def _fmt_date(iso: str) -> str:
    if not iso:
        return "-"
    return iso.replace("T", " ").replace("Z", " UTC").strip()


def _table(headers: list[str], rows: list[list[str]], min_widths: list[int] | None = None):
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], len(str(cell)))
    if min_widths:
        for i, mw in enumerate(min_widths):
            if i < len(widths):
                widths[i] = max(widths[i], mw)
    header_line = "  ".join(str(h).ljust(widths[i]) for i, h in enumerate(headers))
    print(_bold(header_line))
    print("  ".join("─" * w for w in widths))
    for row in rows:
        cells = []
        for i, cell in enumerate(row):
            s = str(cell)
            if i < len(widths):
                cells.append(s.ljust(widths[i]))
            else:
                cells.append(s)
        print("  ".join(cells))


# ── Lazy init ────────────────────────────────────────────────────────────────

_initialized = False

def _init():
    """Initialize all modules and DB. Called once, idempotent."""
    global _initialized
    if _initialized:
        return
    from v2.app.stores import media       # registers schema
    from v2.app.stores import model       # registers schema
    from v2.app.domain import catalog     # registers schema
    from v2.app.core import download    # registers schema
    from v2.app.domain import gallery     # registers schema + callback
    from v2.app.core.db import init_db
    init_db()
    _initialized = True


def _db_conn():
    _init()
    from v2.app.core.db import get_conn
    return get_conn()
