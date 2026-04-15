---
title: Dead Code and Duplication in Provider Manager
date: 2026-04-15
category: logic-errors
module: claude-provider-switcher
problem_type: logic_error
component: service_object
severity: high
symptoms:
  - switch_provider() always returned empty string for backup path
  - Redundant file I/O in get_switch_history() — O(B*P) reads per call
  - api_providers() triggered two independent full scans of all provider files
  - Provider summary dict built identically in 3 separate functions
root_cause: logic_error
resolution_type: code_fix
tags:
  - dead-code
  - code-duplication
  - performance
  - flask
  - file-io
  - provider-switcher
---

# Dead Code and Duplication in Provider Manager

## Problem

`provider_manager.py` contained a logic bug where `switch_provider()` silently discarded backup paths, alongside pervasive code duplication and inefficient file I/O patterns that compounded on every API request.

## Symptoms

- `switch_provider()` returned `"backup": ""` on every successful switch — the backup file was created but its path was never communicated back
- `_backup_settings.__wrapped__()` referenced a `functools.wraps` attribute on a plain function that never had one
- `get_switch_history()` read every provider's `.env` file for every backup entry (O(B\*P) file reads)
- `get_all_providers()` + `get_current_provider()` each independently read `settings.json` and all `.env` files
- The provider summary dict `{id, label, color, icon}` was constructed inline in 3 functions
- The models extraction dict `{haiku, opus, sonnet}` was duplicated in 2 functions

## What Didn't Work

N/A — issues were discovered via static code review (`/simplify`), not runtime debugging.

## Solution

### 1. Fix dead code in `switch_provider()`

Capture the return value of `_backup_settings()` instead of discarding it and attempting to recover via a non-existent `__wrapped__` attribute.

```python
# Before
_backup_settings()
# ... later in return:
"backup": _backup_settings.__wrapped__() if hasattr(_backup_settings, '__wrapped__') else ""

# After
backup_path = _backup_settings()
# ... later in return:
"backup": backup_path
```

### 2. Extract shared helpers to eliminate duplication

```python
def _load_provider_env(name: str) -> dict:
    env_file = PROVIDERS_DIR / f"{name}.env"
    return _load_env_file(env_file) if env_file.exists() else {}

def _provider_summary(name: str, m: dict) -> dict:
    return {
        "id": name,
        "label": m["label"],
        "color": m.get("color", "#888"),
        "icon": m.get("icon", name[0].upper()),
    }

def _extract_models(env: dict) -> dict:
    return {
        "haiku": env.get("ANTHROPIC_DEFAULT_HAIKU_MODEL", ""),
        "opus": env.get("ANTHROPIC_DEFAULT_OPUS_MODEL", ""),
        "sonnet": env.get("ANTHROPIC_DEFAULT_SONNET_MODEL", ""),
    }
```

### 3. Build lookup map to eliminate O(B\*P) file reads

```python
def _build_url_to_provider(meta: dict) -> dict:
    mapping = {}
    for pname in meta:
        env = _load_provider_env(pname)
        url = env.get("ANTHROPIC_BASE_URL")
        if url:
            mapping[url] = pname
    return mapping
```

Used in `get_current_provider()` and `get_switch_history()` — replaces per-backup inner loops with O(1) dict lookups.

### 4. Consolidate `get_all_providers()` to return `current_id`

```python
# Before (app.py) — two full scans
providers = get_all_providers()      # reads meta + all .env files
current = get_current_provider()     # reads settings + meta + all .env files again

# After — single pass
def get_all_providers() -> dict:
    meta = _load_meta()
    settings = _load_settings()
    url_map = _build_url_to_provider(meta)
    current_id = url_map.get(current_url, "unknown")
    # ... build providers list ...
    return {"providers": providers, "current_id": current_id}
```

## Why This Works

- The `__wrapped__` attribute only exists on functions decorated with `functools.wraps`. `_backup_settings` was a plain function, so `hasattr` always returned `False` and the backup path was silently lost.
- The repeated `_load_env_file(PROVIDERS_DIR / f"{name}.env")` pattern was identical in 4 call sites — extracting it to `_load_provider_env()` eliminates both duplication and the risk of path construction drifting.
- `_build_url_to_provider()` trades one O(P) scan for B subsequent O(1) lookups, reducing total file reads from O(B\*P) to O(P+B).
- Returning `current_id` from `get_all_providers()` eliminates a redundant full scan triggered on every page load.

## Prevention

- **Never discard return values you'll need later** — capture `_backup_settings()` return immediately, don't try to recover it via attribute introspection.
- **Extract helpers at the second occurrence** — when the same 3+ line pattern appears in a second function, extract it immediately rather than waiting for a third copy.
- **Build lookup maps before loops** — when matching data across two collections inside a loop, build a dict/lookup from one side first.
- **Audit API endpoints for redundant work** — if two endpoints called from the same page each perform the same expensive operation, consolidate into one call.
