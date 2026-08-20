# PowerBlockade vs Pi-hole vs AdGuard Home

Three tools, three designs, one job: filter DNS. This page compares them honestly — which means it spends as much effort telling you what the numbers *can't* show as what they can. All external data is cited and dated; all PowerBlockade numbers come from committed benchmark artifacts in this repository, with methodology you can re-run yourself.

## How to read these numbers

Before comparing anything, four caveats that materially affect every table below:

1. **Where latency is measured differs.** PowerBlockade's latency figures are measured in-process at the dnsdist edge — pure server processing, no network round-trip. Published Pi-hole and AdGuard Home benchmark numbers are client-side, which includes at least one network round-trip (LAN RTT is typically 0.1–0.5 ms on Gigabit Ethernet — larger than the entire server-side processing time of any of these tools). The published numbers are therefore an upper bound on server processing, not a measurement of it.
2. **Hardware differs across sources.** Different machines, different generations, different loads. No cross-source number is directly comparable.
3. **Concurrency differs.** PowerBlockade's 8,497 QPS figure was produced by a single dnsperf flow — explicitly flow-limited, not a server ceiling. The OxiDNS AdGuard Home numbers use up to 256 outstanding queries. More concurrent flows generally yield higher aggregate throughput for multi-threaded servers.
4. **Dates matter.** Everything below reflects the state of things as of August 2026. Software moves; re-check the sources.

## Throughput

| Tool | QPS | Conditions | Source |
|---|---|---|---|
| AdGuard Home v0.107.78 | 65,556–72,286 | Cache-hit, 64–256 outstanding queries, multi-core (250–260% CPU), strong hardware | [OxiDNS benchmark](https://oxidns.org/en/benchmarks/), 2026 |
| AdGuard Home | ~24,600 | Local dnsperf, single flow, blocking enabled | [GitHub issue #7463](https://github.com/AdguardTeam/AdGuardHome/issues/7463) |
| Pi-hole FTL v6.6.2 | ~900–940 (network-limited) | WAN-based benchmark; **not** a server ceiling | [ConYel dns-sinkhole-bench](https://github.com/ConYel/dns-sinkhole-bench) |
| Pi-hole | not published | No server-limited saturation benchmark exists | — |
| PowerBlockade | **8,497 sustained @ 0.01% errors** | Single dnsperf flow — flow-limited, not a ceiling | `benchmark-20260819-093217.json` (in-repo artifact) |

Notes:

- **Pi-hole's ceiling is architectural, not benchmarked.** Its UDP query path runs on a single thread — confirmed by Pi-hole developer DL6ER: "dnsmasq handles UDP queries in one single thread and there is no way to change this" ([Pi-hole Discourse](https://discourse.pi-hole.net/t/pihole-ftl-only-utilizing-single-core/66744)). No published benchmark saturates it. By analogy with other single-threaded DNS servers (BIND9 measured at 24.6k QPS on one core, [ISC DNS-OARC 42](https://www.isc.org/docs/2024-oarc42-spacek.pdf)), the class is plausibly 10–25k QPS on a fast modern core. **This is an inference, clearly labeled as such — not a measurement.**
- **PowerBlockade's 8,497 is a floor, not a ceiling.** A single dnsperf client flow hashed onto one listener thread (verified during our experiment battery — per-thread counters showed 1.1M queries on one listener, ~0 on the other three). A supplemental four-flow test reached 13,841 QPS with no config change. The multi-threaded C++ edge scales with concurrency; we simply have not yet run a multi-flow saturation campaign on production-class hardware.

## Latency

| Tool | Metric | Value | Conditions | Source |
|---|---|---|---|---|
| PowerBlockade | p50 / p95 / p99 (cache-hit) | **0.049 / 0.093 / 0.147 ms** | In-process at the dnsdist edge, warm path | `benchmark-20260819-093217.json` |
| AdGuard Home v0.107.78 | p99 (cache-hit) | 3.1–7.9 ms | 64–256 outstanding, heavy multi-flow load | [OxiDNS](https://oxidns.org/en/benchmarks/), 2026 |
| AdGuard Home | avg | 3.6 ms | Single flow @ ~25k QPS, blocking on | [GitHub #7463](https://github.com/AdguardTeam/AdGuardHome/issues/7463) |
| Pi-hole 6.0.2 | median / p99 | 28 / 47 ms | Client-side, 1k QPS mixed incl. upstream forwarding | [johal.in](https://johal.in/benchmark-pi-hole-60-vs-adguard-home-40-1k), Apr 2026 |
| AdGuard Home 4.0.1 | median / p99 | 16 / 39 ms | Same conditions | [johal.in](https://johal.in/benchmark-pi-hole-60-vs-adguard-home-40-1k) |
| Pi-hole & AdGuard Home | cache-hit | "< 2 ms" on LAN | Raspberry Pi 4, client-side | [pidiylab.com](https://pidiylab.com/adguard-home-vs-pi-hole-on-raspberry-pi/), Dec 2025 |

The honest reading: **all three serve cache hits faster than a network round-trip.** Our 0.049 ms p50 is server-side processing; the others' "< 2 ms" includes the LAN RTT — server-side, everyone is in the same sub-ms class. What actually differs:

1. **We publish our percentiles with methodology and committed artifacts; the others don't publish server-side percentiles at all.** You can re-run our benchmark suite yourself (`scripts/benchmarks/dns53-benchmark.sh`).
2. **Behavior under load.** PowerBlockade's p99 held ~0.2 ms at 8.5k QPS (single flow); AdGuard Home's published p99 under heavy multi-flow load is 3–8 ms. Different conditions — but if you care about tails under load, only one of these stacks shows you the tail.
3. **The measurement itself is a feature.** PowerBlockade ships a sub-millisecond latency histogram (0.1–10 ms buckets) as a native Prometheus metric, with synthetic prober traffic kept on separate series from production traffic, so your Grafana dashboard shows the tail continuously — not just on benchmark day.

## Architecture

| | Pi-hole v6 | AdGuard Home | PowerBlockade |
|---|---|---|---|
| Core | FTLDNS (dnsmasq fork), C, monolithic binary | Single Go binary (`dnsproxy`), goroutine pool | dnsdist 2.0.8 edge + PowerDNS Recursor 5.3.10, multi-threaded C++ |
| UDP query path | Single thread (confirmed by developer) | Multi-core (Go runtime) | Multi-threaded, `reuseport` listeners |
| Resolution model | Forwarding proxy (Unbound sidecar for recursion) | Forwarding proxy | **Full recursive resolver built in, DNSSEC validation** |
| Cache | In-memory hash, default 10k entries (cap removed in fork) | In-memory (Go), undocumented default | 500k edge packet cache + 1M packet + 2M record cache entries, deliberate |
| Query log | SQLite | In-memory ring + JSONL files (no SQL backend) | PostgreSQL, partitioned, with rollups |
| Cold-start | Empty cache on restart | Empty cache on restart | Pair-based boot warm burst; measured 185 s to stably-warm |

## Feature matrix

| Feature | Pi-hole v6 | AdGuard Home | PowerBlockade |
|---|---|---|---|
| Blocklist formats | Hosts, Adblock Plus, regex, groups | Hosts, Adblock, rewrites, per-client, parental | RPZ zones from Pi-hole-compatible lists, manual allow/block |
| Full recursion | Via Unbound sidecar | Via upstream config | **Built in** |
| Split DNS (forward zones) | No | Upstream config | **Yes** |
| Query log analytics | Web UI over SQLite | Web UI over ring buffer | **Postgres-backed search, rollups, per-client/domain analytics** |
| Multi-node / HA | Community sync scripts | Community patterns | **First-class: secondary packages, config sync, heartbeats, node health** |
| Prometheus metrics | Third-party exporter | Third-party exporter (native endpoint merged but unreleased as of mid-2026) | **Native, five services, sub-ms latency histogram** |
| Grafana dashboards | Via exporter | Via exporter | **Provisioned out of the box** |
| Serve stale during outage | Up to 1 h past TTL (cache optimizer) | Not documented | **300 s, verified during a live outage test** |
| DHCP server | Yes | Yes | No (documented non-goal) |
| DoH/DoT/DoQ listeners | DoH server in v6 | Built in | Via dnsdist config (supported, not default) |
| Memory footprint | ~80–200 MB | ~50–300 MB | ~1–2.5 GB by design |

## Where PowerBlockade is deliberately different

**A resolver, not a proxy.** Pi-hole and AdGuard Home forward to an upstream resolver; recursion in those setups means bolting on Unbound. PowerBlockade *is* the recursive resolver — full iterative resolution and DNSSEC validation in the box, with the edge cache in front of it.

**Speed you can audit.** The 0.147 ms warm-path p99 isn't a marketing number; it's a committed JSON artifact with a fail-closed benchmark harness that clears both cache layers before measuring and gates on p99. The same harness caught and fixed a silently broken stale-serving config that had been capping outage tolerance at 31 seconds.

**Caching as an engineering discipline.** Two cache layers tuned for a 99.9% edge hit ratio; warming that learns which (domain, record-type) pairs your network actually asks for — including HTTPS/65 records that browsers query constantly — and refreshes them through the edge ahead of TTL expiry; a rate-limited boot burst that refills caches after a restart in minutes (measured: 185 seconds to stably warm).

**Analytics-grade logging.** Query history in partitioned PostgreSQL with hourly/daily rollups — search and per-client/per-domain analytics that stay fast with years of history, instead of a SQLite file or a JSONL log.

**Multi-node as a first-class citizen.** Generate a secondary-node package from the admin UI, deploy it on another host, and it registers, syncs blocklists and config, ships its query log back to the primary, and appears in node health dashboards. No community sync scripts.

**Observability without exporters.** Five services expose Prometheus metrics natively, including the only sub-millisecond latency histogram in this comparison, with synthetic prober traffic isolated from production series so the numbers you graph are the numbers your clients experience.

## What PowerBlockade gives up

Honesty section, no hedging:

- **Memory.** ~1–2.5 GB by design, versus ~50–300 MB for tools built to run on a Raspberry Pi. We trade RAM for a 99.9% hit ratio across 3.5M cache entries and a real database. If your host has 1 GB total, choose the other tools.
- **Simplicity of deployment.** A multi-container stack (DNS edge, recursor, processor, admin UI, database, metrics) versus a single binary or one-command installer. More moving parts, more things to understand.
- **DHCP.** Pi-hole and AdGuard Home both include DHCP servers. PowerBlockade deliberately does not (see PROJECT.md non-goals).
- **Encrypted-DNS listeners out of the box.** AdGuard Home serves DoH/DoT/DoQ/DNSCrypt from its single binary; Pi-hole v6 has a DoH server. PowerBlockade's dnsdist supports all of these but our default compose ships plain DNS on :53 — enabling them is a config change, not a checkbox.
- **Scale of community.** Pi-hole and AdGuard Home have enormous user bases and ecosystems of guides and integrations. We are a young project.

## Sources

- PowerBlockade: `docs/performance/results/benchmark-20260819-093217.json`, `docs/performance/results/benchmark-time-to-warm-official.json`, `docs/performance/experiment-log.md`, `docs/performance/dns-benchmark-methodology.md` (all in this repository; methodology re-runnable via `scripts/benchmarks/dns53-benchmark.sh`)
- OxiDNS benchmark (2026): https://oxidns.org/en/benchmarks/ — AdGuard Home v0.107.78 throughput/latency/RSS
- AdGuard Home GitHub issue #7463: https://github.com/AdguardTeam/AdGuardHome/issues/7463 — single-flow throughput with blocking
- Pi-hole Discourse (DL6ER on threading): https://discourse.pi-hole.net/t/pihole-ftl-only-utilizing-single-core/66744
- ISC DNS-OARC 42 (BIND9 single-thread): https://www.isc.org/docs/2024-oarc42-spacek.pdf
- ConYel dns-sinkhole-bench: https://github.com/ConYel/dns-sinkhole-bench — multi-sinkhole WAN benchmark
- johal.in (April 2026): https://johal.in/benchmark-pi-hole-60-vs-adguard-home-40-1k — Pi-hole vs AGH client-side latency
- pidiylab.com (Dec 2025): https://pidiylab.com/adguard-home-vs-pi-hole-on-raspberry-pi/ — Raspberry Pi comparison
- Pi-hole cache docs: https://docs.pi-hole.net/ftldns/dns-cache/
- AdGuard Home tech doc (query log backend): https://github.com/AdguardTeam/AdGuardHome/blob/master/AGHTechDoc.md
- AdGuard Home Prometheus PR: https://github.com/AdguardTeam/AdGuardHome/issues/516

*Comparisons reflect information available as of August 2026.*
