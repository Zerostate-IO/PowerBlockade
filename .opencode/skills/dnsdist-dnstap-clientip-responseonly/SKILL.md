---
name: dnsdist-dnstap-clientip-responseonly
description: |
  Use when adding dnsdist in front of PowerDNS Recursor to get true client IP attribution
  and dnstap-based “Pi-hole-like” logging. Covers common docker/dnsdist gotchas:
  (1) dnsdist container entrypoint/command pitfalls, (2) dnsdist newServer() not accepting
  hostnames like recursor:5300, (3) dnstap CLIENT_* field mapping where QueryAddress is the
  downstream client and ResponseAddress is dnsdist itself, and (4) ingesting CLIENT_RESPONSE
  only to avoid query/response duplicates.
---

# dnsdist + dnstap: true client IP + response-only logging

## Problem
PowerDNS Recursor-side logging (e.g. protobufServer or recursor-emitted dnstap) often cannot
reliably attribute queries to the real LAN client IP because the Recursor may only see an
intermediary (forwarder/load balancer/dnsdist).

## Context / Trigger Conditions
- You want Pi-hole-like query logs with correct client IPs.
- Recursor protobuf logging shows `from` as upstream/public IPs rather than LAN clients.
- You introduce dnsdist in Docker and hit either:
  - `Fatal pdns error: Unable to convert presentation address 'dnsdist'` (entrypoint/command mismatch)
  - `Unable to convert presentation address 'recursor:5300'` (dnsdist newServer hostname parsing)
  - Logged client IP equals dnsdist container IP (using ResponseAddress instead of QueryAddress)

## Solution

### 1) Put dnsdist at the edge (bind host :53)
- dnsdist listens on `0.0.0.0:53` (TCP/UDP) on the host.
- Recursor listens on an *internal* port (e.g. 5300) only on the docker network.

### 2) dnsdist docker entrypoint gotcha
Some dnsdist images have an entrypoint wrapper that treats the first argv token as an address.

**Fix:** override entrypoint explicitly to `dnsdist` and pass config via `--supervised -C ...`.

### 3) dnsdist backend server address gotcha
`newServer({ address = 'recursor:5300' })` can fail because dnsdist parses it as a literal
presentation address.

**Fix:** assign a static IP to the recursor container on the compose network and use that IP
in `newServer()`.

### 4) dnstap field mapping (dnsdist)
For dnsdist-generated dnstap `CLIENT_*` messages:
- **Downstream client IP/port**: `QueryAddress` / `QueryPort`
- **dnsdist local bind**: `ResponseAddress` / `ResponsePort`

If you use `ResponseAddress` as the “client”, you’ll log dnsdist’s IP, not the LAN device.

### 5) Response-only ingestion to avoid duplicates
To keep logs “one row per answered query/qtype”, ingest only `CLIENT_RESPONSE` events.

Tradeoff: no record for queries that never receive a response (timeouts/drops). If needed,
add a query-timeout fallback that inserts a query after N ms without a matching response.

## Verification
1) `docker compose up -d --build`
2) Generate a query from a container on the compose network:
   - `docker run --rm --network powerblockade busybox:1.36 nslookup example.com dnsdist`
3) Confirm Postgres events contain the real container IP (not upstream/public IP):
   - `docker exec powerblockade-postgres psql -U powerblockade -d powerblockade -c "select ts, client_ip, qname, qtype, rcode from dns_query_events order by ts desc limit 10;"`

## Example
- Compose:
  - dnsdist publishes host `53/tcp` and `53/udp`
  - recursor uses `local-port=5300` and is not published on host `:53`
  - shared `dnstap-socket` volume mounted at `/var/run/dnstap`

## Notes
- If the socket consumer (dnstap-processor) restarts, you may need to restart dnsdist to
  re-open the AF_UNIX framestream socket cleanly (depending on how dnsdist handles reconnect).
