---
name: dnsdist-dnstap-client-ip-compose
description: |
  Use when running PowerDNS dnsdist in docker-compose and wiring dnstap to a local UNIX framestream socket.
  Covers: (1) dnsdist-19 Docker image entrypoint gotcha causing "Unable to convert presentation address 'dnsdist'" when you pass a command,
  (2) dnsdist newServer() requiring an IP literal (hostnames like recursor:5300 fail),
  (3) dnstap CLIENT_RESPONSE address fields: QueryAddress is the downstream client; ResponseAddress is the local bind (dnsdist).
---

# dnsdist + dnstap client IP gotchas (docker-compose)

## Problem
You add dnsdist in front of a Recursor to get true client attribution, but:

1) dnsdist container restarts with:
   - `Fatal pdns error: Unable to convert presentation address 'dnsdist'`

2) dnsdist refuses backend hostnames:
   - `Error creating new server with address recursor:5300: Unable to convert presentation address 'recursor:5300'`

3) Your dnstap consumer stores the wrong `client_ip` for responses (often the dnsdist IP instead of the real client).

## Context / Trigger Conditions
- Using Docker Hub image `powerdns/dnsdist-19:latest`
- You try to set a compose `command:` like `["dnsdist", "--supervised", "-C", "/etc/dnsdist/dnsdist.conf"]`
- You use dnsdist dnstap via `newFrameStreamUnixLogger('/var/run/dnstap/dnstap.sock')` and `DnstapLog*Action()`

## Solution

### 1) Bypass the image entrypoint wrapper
The `powerdns/dnsdist-19` image entrypoint is `dnsdist-startup` (via `tini`).
If you set `command: ["dnsdist", ...]`, those args get passed to the wrapper, not executed as the binary.

Fix by overriding entrypoint:

```yaml
dnsdist:
  image: powerdns/dnsdist-19:latest
  entrypoint: ["dnsdist"]
  command: ["--supervised", "-C", "/etc/dnsdist/dnsdist.conf"]
```

### 2) Use an IP literal for newServer()
`newServer({ address='recursor:5300' })` fails because dnsdist expects an IP literal.
Pin the recursor container to a static IP on the compose network and use that.

```yaml
recursor:
  networks:
    default:
      ipv4_address: 172.30.0.10
```

```lua
newServer({ address='172.30.0.10:5300', name='recursor' })
```

### 3) For dnsdist CLIENT_RESPONSE, use QueryAddress as the client
In dnstap emitted by dnsdist:
- `QueryAddress/QueryPort` = downstream client
- `ResponseAddress/ResponsePort` = dnsdist local bind

So when ingesting `CLIENT_RESPONSE`, do **not** treat `ResponseAddress` as the client IP.
Use `QueryAddress` for both `CLIENT_QUERY` and `CLIENT_RESPONSE`.

## Verification
1) `docker ps` shows dnsdist stays `Up` (not restarting).
2) Run a query from a client container:
   - `docker run --rm --network <net> busybox:1.36 nslookup example.com <dnsdist-ip>`
3) In your dnstap consumer logs (when debug enabled), confirm:
   - `CLIENT_QUERY qaddr=<client-ip>:<port> raddr=<dnsdist-ip>:53`
   - `CLIENT_RESPONSE qaddr=<client-ip>:<port> raddr=<dnsdist-ip>:53`
4) Confirm stored events have `client_ip=<client-ip>`.

## Notes
- If you restart the dnstap consumer that owns the UNIX socket, you may need to restart dnsdist so it reconnects.

## References
- https://hub.docker.com/r/powerdns/dnsdist-19
- https://www.dnsdist.org/reference/dnstap.html
- https://www.dnsdist.org/reference/actions.html
