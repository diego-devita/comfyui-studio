# Code Standards — v2/app/

Rules for all Python code in this directory. Every file must pass these checks.

## 1. Import discipline

- **No circular imports.** Dependency direction: core → stores → clients → domain → cli. Never backward.
- **No inline repeated imports.** If a module is used in multiple functions, import once at the top or via a single helper function (`_ms()`, `_cat()`).
- **No imports from wrong level.** core/ never imports from stores/, domain/, clients/, or cli/.
- **Lazy imports only when necessary** — to avoid circular deps or heavy startup cost. Document why with a comment.

## 2. No hardcoded values

- **Paths, URLs, ports, credentials** must come from `core/settings.py`. Never hardcode `/workspace`, `8188`, API keys, etc.
- **Magic numbers** get named constants. Exception: 0, 1, -1 in obvious contexts.

## 3. SQL discipline

- **CLI files** may use direct SQL only for diagnostic commands (doctor, verify, dedup) that do full-table scans.
- **Everything else** must use functions from the owning module. CLI calls domain, domain calls stores, stores do SQL.
- **No raw f-string SQL with user input** — always use `?` placeholders.

## 4. Documentation

- **Every function has a docstring.** Explains what it does, not how. One line for simple functions, multi-line for complex ones.
- **Module docstring** at the top of every file: what the module does, which tables it owns, what it depends on.
- **Section headers** group related functions with visual separators.

## 5. Function organization

- **Grouped by purpose** with section headers (Schema, Helpers, Core operations, Queries, Stats, etc.).
- **Reading order:** private helpers first (`_foo`), then the public functions that use them.
- **Macro after micro:** if function A calls function B, B appears before A in the file.

## 6. No duplication

- **Same logic in one place.** If two functions do similar things, extract the common part into a helper.
- **Callback args built by one function** (`_build_callback_args`), not copy-pasted across callers.

## 7. Error handling

- **try/except only where needed** — at boundaries (HTTP calls, file I/O, DB transactions), not everywhere.
- **DB transactions:** if multiple writes must be atomic, use explicit commit/rollback.
- **Non-fatal failures** (e.g. fetching CivitAI metadata) should not abort the entire operation.

## 8. Naming conventions

- **Functions:** `get_X` (single item), `find_X` (search/filter), `list_X` (all items), `create_X`, `update_X`, `delete_X`.
- **Private functions:** prefixed with `_`. Not called from outside the module.
- **Boolean fields:** `is_X`, `has_X` in the DB schema. Python functions return `bool` explicitly.
- **IDs:** always `str` (UUIDs as hex). CivitAI IDs are `int` in API calls, `str` when stored.

## 9. No dead code

- **No unused imports.** No commented-out code. No functions that nothing calls.
- **No TODO comments** without a corresponding entry in .context/project/todo.md.

## 10. Return type consistency

- **Single item:** `dict | None` (None = not found).
- **List:** `list[dict]` (empty list = no results, never None).
- **Count:** `int`.
- **Success/failure:** `bool`.
- **ID of created entity:** `str`.

## 11. Timestamps

- **Always UTC.** Format: `YYYY-MM-DDTHH:MM:SSZ` (ISO 8601).
- **Use `now_iso()` from settings.** Never `datetime.now()` directly.

## 12. File structure template

```python
"""Module name — what it does.

Longer description of purpose, what tables it owns,
what it depends on.
"""

import stdlib
import third_party
from v2.app.core import ...

# ══════════════════════════════════════════════════════════════════════════════
#  SECTION NAME
# ══════════════════════════════════════════════════════════════════════════════

def _private_helper():
    """What it does."""
    ...

def public_function():
    """What it does."""
    ...
```
