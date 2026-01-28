---
name: pdns-recursor-compose-gotchas
description: |
  Use when PowerDNS Recursor dnstap framestream produces 0 events or a rec_control reloader sidecar keeps restarting under Docker Compose.
  Trigger symptoms: (1) dnstap collector shows recv_total=0 while the unix socket exists, (2) recursor has no obvious dnstap error logs,
  (3) a sidecar meant to run `rec_control reload-*` restarts with “Fatal: non-options (sh, while true; do ...)” or shell syntax errors.
  Fixes unix socket permissions (chmod 0666) and correct Compose entrypoint scripting.
---

# PowerDNS Recursor Compose Gotchas

## Problem

1) **dnstap framestream over unix socket yields 0 events** even though the socket path exists.

2) **recursor-reloader sidecar** (a loop running `rec_control reload-zones` / `reload-lua-config`) **keeps restarting** because the image’s default entrypoint is still `pdns_recursor` and your shell loop is being passed as CLI args.

## Context / Trigger Conditions

### A. dnstap no events

- Recursor configured with Lua `dnstapFrameStreamServer("/var/run/dnstap/dnstap.sock", {logQueries=true, logResponses=true})`
- Collector uses `github.com/dnstap/golang-dnstap` `NewFrameStreamSockInputFromPath("/var/run/dnstap/dnstap.sock")`
- Collector logs show `recv_total=0` over time.
- `ls -l /var/run/dnstap/dnstap.sock` shows it exists, often owned by `root:root` and mode like `srwxr-xr-x`.

### B. recursor-reloader restart loop

- Container logs show errors like:
  - `Fatal: non-options (sh, while true; do ...) on the command line...`
  - or repeated `Syntax error: end of file unexpected (expecting "do")`.

## Solution

### A. Fix unix socket permissions for dnstap

**Root cause:** the collector (server) creates the unix socket file with restrictive perms (often `0755` owned by root). Recursor may not run as root, so it cannot `connect()` to the socket. Recursor may also not log a clear error.

**Fix:**

1. Ensure the socket directory is permissive (in recursor container entrypoint is fine):

```sh
mkdir -p /var/run/dnstap
chmod 0777 /var/run/dnstap || true
```

2. After the collector binds the socket, `chmod` the socket to allow connects:

```go
input, err := dnstap.NewFrameStreamSockInputFromPath(cfg.DnstapSocket)
if err != nil { /* ... */ }
_ = os.Chmod(cfg.DnstapSocket, 0o666)
```

### B. Compose shell loop for rec_control: override entrypoint correctly

**Root cause:** `powerdns/pdns-recursor-*` images use an entrypoint that starts `pdns_recursor` (often via `tini`). If you only set `command: sh -c ...`, Docker will pass `sh -c ...` as args to `pdns_recursor`.

**Fix:** override the **entrypoint** to `sh -c <script>` so the shell actually runs:

```yaml
recursor-reloader:
  image: powerdns/pdns-recursor-51:latest
  entrypoint:
    - sh
    - -c
    - >-
      while true; do
        rec_control --socket-dir=/var/run/pdns-recursor reload-zones || true;
        rec_control --socket-dir=/var/run/pdns-recursor reload-lua-config || true;
        sleep ${RECURSOR_RELOAD_INTERVAL_SECONDS:-5};
      done
```

Putting the script in `entrypoint` (3rd arg) avoids Compose splitting/truncating multiline `command` strings.

## Verification

### dnstap

- On recursor container:
  - `ls -ld /var/run/dnstap` shows mode `drwxrwxrwx` (or equivalent).
  - `ls -l /var/run/dnstap/dnstap.sock` shows mode `srw-rw-rw-` (or at least writable by recursor user).
- Collector logs show `recv_total>0` and message samples (types like `RESOLVER_QUERY/RESOLVER_RESPONSE`).

### recursor-reloader

- `docker compose ps` shows reloader status `Up` (not restarting).
- Logs show `ok` / `Reloaded Lua configuration file ...` instead of fatal CLI parsing errors.

## Notes

- PowerDNS Recursor 5.x config behavior: `recursor.conf` may be attempted as YAML first; if it fails, it may fall back to old-style (5.1.x). From 5.2.0+, old-style requires `--enable-old-settings`.
- If your goal is **per-LAN-client query logging**, Recursor dnstap framestream emits resolver-side traffic (types like `RESOLVER_*`), not necessarily end-client IP. You may need protobuf logging or an alternative approach for true client attribution.

## References

- PowerDNS Recursor docs: dnstap framestream Lua config (`dnstapFrameStreamServer`): https://doc.powerdns.com/recursor/lua-config/protobuf.html
- PowerDNS Recursor docs: YAML settings behavior / 5.x config migration notes: https://doc.powerdns.com/recursor/yamlsettings.html
