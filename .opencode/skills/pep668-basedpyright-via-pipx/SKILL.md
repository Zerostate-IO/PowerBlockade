---
name: pep668-basedpyright-via-pipx
description: |
  Use when LSP diagnostics fail with "basedpyright-langserver: command not found" and installing via pip hits PEP 668 "externally-managed-environment". Installs basedpyright safely via pipx so the LSP server is globally available without breaking system Python.
---

# PEP 668 basedpyright via pipx

## Problem

Python LSP is configured for `basedpyright`, but `basedpyright-langserver` is not installed.

Attempting `python3 -m pip install basedpyright` on macOS/Homebrew Python fails with:

- `error: externally-managed-environment`

## Context / Trigger Conditions

- LSP error:
  - `LSP server 'basedpyright' is configured but NOT INSTALLED.`
  - `Command not found: basedpyright-langserver`
- Pip error:
  - `externally-managed-environment` (PEP 668)

## Solution

Install `basedpyright` as an isolated application using `pipx`:

```bash
pipx install basedpyright
```

This makes these binaries available on PATH:

- `basedpyright`
- `basedpyright-langserver`

## Verification

1) Confirm binaries are available:

```bash
command -v basedpyright-langserver
```

2) Re-run LSP diagnostics (editor/LSP): imports should resolve.

## Notes

- Prefer `pipx` over `--break-system-packages` to avoid destabilizing Homebrew Python.
