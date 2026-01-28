---
name: docker-compose-env-backslash-escape
description: |
  Use when `docker compose` fails reading `.env` with errors like "unexpected character '\\' in variable name" due to accidental backslashes inserted by env-generation scripts (e.g., perl replacements). Fix by ensuring `.env` contains plain KEY=VALUE lines with no escaping and generate values using safe character sets.
---

# Docker Compose `.env` backslash escape pitfalls

## Problem

`docker compose` reads `.env` and fails with something like:

```
failed to read .../.env: line N: unexpected character "\\" in variable name
```

## Context / Trigger Conditions

- An onboarding script generates `.env` values.
- The script uses an escaping mechanism (e.g., Perl `\Q...\E`) that writes backslashes into the file:
  - `FOO\=bar` instead of `FOO=bar`
  - `value\-with\-dashes` instead of `value-with-dashes`

## Solution

1) Fix `.env` lines to be plain `KEY=VALUE` (remove backslashes).

2) Fix the generator to avoid over-escaping. Example (Perl):

```bash
perl -0777 -i -pe "s/^KEY=\$/KEY=${VALUE}/m" .env
```

3) Prefer generating secrets using URL-safe alphabets (letters, digits, `-`, `_`) to avoid needing escaping.

## Verification

```bash
docker compose config -q
```

Should exit 0.
