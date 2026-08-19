# Performance Experiment Battery — 2026-08-19

Session-scoped experiment battery (packet P8) on the `perf/integration` live
stack (worktree `pb-wt-int`). Each experiment changes exactly one thing,
benchmarks with `scripts/benchmarks/dns53-benchmark.sh`, and compares against
both the committed official baseline and a same-session anchor run.

## Reference numbers

| Run | Config | Sat QPS | Sat p99 (ms) | Sat err % | Warm p50/p95/p99 (ms) | Warm dnsdist hit % |
|---|---|---|---|---|---|---|
| Official baseline (`results/benchmark-20260819-093217.json`) | 1 listener, sockets=4, ECS on, threads=4 + distributor | 8497 | 0.191 | 0.01 | 0.049 / 0.093 / 0.147 | 99.9 |
| Same-session anchor (this battery, same config) | idem | 8597 | 0.231 | 0.00 | 0.049 / 0.101 / 0.203 | 100.0 |

Noise band derived from the two same-config runs: ±1.2% saturation QPS,
±0.04 ms saturation p99, ±0.06 ms warm p99. **Decision rule:** a change is
kept only when it wins by more than ±3% QPS or a clear (>2× noise) latency
margin; flat or negative results are reverted and recorded.

Prober: stopped for the whole battery (verified `docker compose ps prober`
empty). Harness: `--mode` per phase, console clear mode, precache job paused
by the harness and restored.

---

## E1 — Parallelism

### E1a — dnsdist: 1 → 4 `reusePort` listeners

- **Hypothesis:** one UDP listener thread caps receive-side parallelism; four
  identical `setLocal/addLocal` bindings let the kernel spread flows across
  four listener threads (dnsdist 2.0.8: `setLocal` clears + adds, `addLocal`
  appends; `reusePort=true` required on every binding).
- **Change:** `dnsdist.conf.template`: `setLocal('0.0.0.0:53', {reusePort=true})`
  plus three `addLocal('0.0.0.0:53', {reusePort=true})`.
- **Verification of bind:** `getBindCount()` = 8 (4 UDP + 4 TCP), dnsdist log
  shows 4 × `Listening on 0.0.0.0:53`, `/proc/net/udp` in the container netns
  contains exactly 4 sockets on `:0035`, `dig` answers through the edge.
- **Numbers (official harness):**

  | Metric | Anchor (1 listener) | E1a (4 listeners) |
  |---|---|---|
  | Saturation QPS | 8597 | 8590 (−0.08%) |
  | Saturation p99 (ms) | 0.231 | 0.123 |
  | Saturation errors | 0.00% | 0.00% |
  | Warm p50/p95/p99 (ms) | 0.049 / 0.101 / 0.203 | 0.050 / 0.089 / 0.135 |
  | Warm dnsdist hit % | 100.0 | 99.9 |

- **Per-thread evidence (`dnsdist_frontend_queries{thread=...}` from /metrics):**
  after the single-flow official saturation run, thread 2 = 1,303,335 queries
  while threads 0/1/3 = 12973 / 2 / 25946 (latter numbers from the harness's
  own warmup bursts) — the kernel hashes the one dnsperf flow onto exactly one
  listener, so the official harness structurally cannot show a listener win.
- **Supplemental multi-flow test (NOT the official harness; decision support):**
  4 concurrent `dnsperf -Q 4000` processes for 60 s over the same corpus:
  4 listeners → 13,805 QPS aggregate, 0.02% loss (flows spread onto 2 of the 4
  listeners, ~414k queries each); 1 listener → 13,841 QPS aggregate, 0.00%
  loss. Difference 0.3% = noise. **A single dnsdist listener thread sustains
  ≥13.8k QPS on this host**; the official 8.5k saturation figure is bounded by
  the single-flow dnsperf client, not by dnsdist receive parallelism.
- **Verdict: REVERT.** No measurable win on the official harness (QPS flat,
  p99 within noise) and no win under 4-flow client diversity. Keeping one
  `setLocal` binding preserves the simpler config. Rolled back in the working
  tree and verified (getBindCount()=2 again).

### E1b — dnsdist: backend `sockets` 4 → 8

- **Hypothesis:** docs recommend backend sockets ≈ 2 × recursor threads
  (4 threads → 8 sockets) to remove the per-socket queue as a bottleneck.
- **Change:** `newServer({... sockets=8 ...})`, dnsdist force-recreated
  (verified: 2 listeners from E1a revert, dig answers).
- **Numbers (official harness, saturation):**

  | Metric | Anchor (sockets=4) | E1b (sockets=8) |
  |---|---|---|
  | Saturation QPS | 8597 | 8558 (−0.45%) |
  | Saturation p99 (ms) | 0.231 | 0.227 |
  | Saturation errors | 0.00% | 0.00% |

- **Verdict: REVERT.** Flat on every axis (deltas inside the ±1.2% same-config
  noise band). At saturation the edge packet cache answers ~99.9% of queries,
  so backend socket pressure is near zero by construction — the 4→8 socket
  change cannot move the official number behind this cache hit ratio.
  Template restored to `sockets=4` (diff-verified identical to pre-battery).

### E1c — recursor: `pdns-distributes-queries=no`

- **Hypothesis:** with `reuseport=yes` (already set) and the distributor off,
  each recursor worker thread opens its own listening socket and the kernel
  distributes queries directly (upstream docs: "much higher performance on
  multi-core boxes", avoiding the distributor-thread bottleneck and thundering
  herd).
- **Change:** `pdns-distributes-queries=no` in `recursor.conf.template`;
  recursor + dnsdist force-recreated (dnsdist depends on recursor health).
- **Verification of topology:** `/proc/net/udp` in the recursor netns shows 4
  sockets on :5300 (0x14B4) with `distributes-queries=no` vs 1 with it on;
  `rec_control ping` → `pong worker`; harness baseline captured 6
  `cpu-msec-thread-*` counters (worker threads now receive directly).
- **Numbers (official harness, saturation):**

  | Metric | Anchor (distributor on) | E1c (distributor off) |
  |---|---|---|
  | Saturation QPS | 8597 | 8410 (−2.2%) |
  | Saturation p99 (ms) | 0.231 | 0.239 |
  | Saturation errors | 0.00% | 0.01% |

- **Verdict: REVERT.** No win — slightly negative on QPS (−2.2%, at/just
  outside the noise band), p99 and errors flat-to-worse. Structural reason:
  behind a ~99.9% dnsdist hit ratio, only ~0.1% of saturation traffic reaches
  the recursor (its per-thread CPU was 1–4 ms per thread over the whole run),
  so the recursor's receive architecture is nowhere near its bottleneck and
  the per-query distributor hop is invisible. Template restored to
  `pdns-distributes-queries=yes` (verified: 1 :5300 socket again, healthy).

**E1 summary: all three parallelism changes reverted — the stack's official
harness numbers are bounded by the single-flow dnsperf client and the ~99.9%
edge cache, not by listener, backend-socket, or recursor-distributor
parallelism.**

---

## E2 — ECS off at the edge — **VERDICT: KEEP**

- **Hypothesis:** `useClientSubnet=false` stops dnsdist appending ECS options
  on upstream queries. /24-truncated ECS keys mean single-subnet clients share
  packet-cache keys anyway, so the edge hit ratio should not move (overhead
  removal only, small win possible).
- **Change:** `newServer({ ... useClientSubnet=false ... })` in
  `dnsdist.conf.template` (with an inline comment pointing here); dnsdist
  force-recreated, healthy, dig verified.
- **Source-verified rationale (why this is dead overhead):**
  - dnsdist 2.0.8 `dnsdist.cc:1445`: the backend's `useECS` gates the only
    live ECS path (`handleEDNSClientSubnet` → `generateECSOption` per miss).
    With the backend flag off, nothing ECS-related runs on the query path.
  - The zero-scope branch next to it is inert for us: it requires the packet
    cache's `parseECS=true` (`dnsdist-cache.hh:84`), and our `newPacketCache`
    does not set it (default false).
  - Recursor 5.3.10 defaults: `use-incoming-edns-subnet=false` (table.py:3212,
    default `'false'`) and `edns-subnet-allow-list` empty (default `''`,
    table.py:936–950: "By default, this option is empty, meaning no EDNS
    Client Subnet information is sent"). Together: the recursor never parses
    the ECS dnsdist sent and never forwards ECS to authorities — the option was
    constructed, inserted, and discarded per cache miss.
  - Live counters before and after: `pdns_recursor_ecs_queries 0`,
    `ecs_responses 0`, `ecs_missing 0` (recursor /metrics) — the recursor
    side never saw ECS traffic in either config. `rec_control trace-regex`
    question logs show `ecs=""` in both configs (the recursor masks incoming
    ECS because `g_useIncomingECS=false`; dnsdist.cc:1445 is the operative
    proof of what was sent).
- **Numbers (official harness, warm):**

  | Metric | Official baseline | Anchor (ECS on) | E2 (ECS off) |
  |---|---|---|---|
  | Warm p50 (ms) | 0.049 | 0.049 | 0.048 |
  | Warm p95 (ms) | 0.093 | 0.101 | 0.099 |
  | Warm p99 (ms) | 0.147 | 0.203 | 0.187 |
  | Warm dnsdist hit % | 99.9 | 100.0 | 99.9 |
  | Queries lost | 0 | 0 | 0 |

- **Verdict: KEEP (change retained in the tree).** Hit ratio is unchanged —
  the /24-truncation prediction held exactly (no cache-key fragmentation for
  single-subnet clients). p99 improved 0.203 → 0.187 ms vs the same-session
  anchor (−8%, at the edge of the ±0.06 ms noise band; honestly: flat-to-
  slightly-positive). The keep rests on dead-overhead removal: source-verified
  per-miss work that could never affect answers, with zero measured downside
  (0 lost, ratio identical, phase passed). Rollback if ever needed: flip
  `useClientSubnet` back to `true` and recreate dnsdist.

---

## E3 — `refresh-on-ttl-perc=10` (recursor) — **VERDICT: REVERT (no measurable benefit behind dnsdist)**

- **Hypothesis:** near-expiry record/packet-cache entries get background
  refresh tasks, so future queries never wait on an expired entry.
- **Directive name verified** against the 5.3.10 sources
  (`/tmp/opencode/pdns-rec-5.3.10`): `refresh-on-ttl-perc` (table.py
  `refresh_on_ttl_perc`, added 4.5.0, default 0, no separate old-style name;
  the upstream regression suite itself runs it with `--enable-old-settings`).
  The container starts with `--enable-old-settings`; an unknown directive
  aborts startup (rec-main.cc parse path), so "recreated + healthy + directive
  present in the rendered config" proves acceptance. (A pre-existing
  ERROR-level "YAML config found, but error occurred processing it" line
  appears on every start of this ini-style setup and is unrelated.)
- **Direct counter discovered:** `taskqueue-pushed` / `taskqueue-expired` /
  `taskqueue-size` (recursor metrics) count refresh tasks pushed by
  `pushRefreshTask` (recursor_cache.cc `fakeTTD`) — a refresh-firing signal
  that needs no inference.
- **Method:** identical 240 s steady loads at 500 QPS target (~432 QPS
  effective) over the corpus, admin-ui precache job paused via the same
  settings-row mechanism the harness uses (restored after). AFTER side primed
  60 s first so its window is steady-state like BEFORE.
- **Numbers (recursor `rec_control get` deltas over the 240 s window):**

  | Window | all-outqueries Δ | cache-misses Δ | taskqueue-pushed Δ |
  |---|---|---|---|
  | BEFORE (refresh off) | +714 | +528 | +0 |
  | AFTER (refresh=10) | +440 | +367 | **+0** |

  One refresh task fired during the AFTER primer (taskqueue-pushed 0→1 in the
  60 s fill), then zero additional tasks in the 240 s window (~104k queries
  served). No outqueries-without-misses signal appeared in the window.
- **Mechanism (why it cannot fire here):** dnsdist edge entries and recursor
  record entries are created by the same miss at the same instant and age in
  lockstep; when the edge entry finally expires, the query that reaches the
  recursor finds the inner entry either still comfortably fresh or already
  expired — almost never inside the "≤10% TTL remaining" band that triggers a
  refresh task. The shielding caveat predicted exactly this.
- **Verdict: REVERT.** Benefit ≈ one background refetch per 5 min (zero client
  impact); cost ≈ zero — flat in both directions, so per the decision rule
  (keep only measured wins) the directive is removed and the simpler config
  retained. Rollback state: template restored (directive absent, diff clean),
  recursor+dnsdist recreated and healthy, precache settings row removed
  (app default re-applies).

---

## E4 — Stale depth 60/60 → 300/300 — **VERDICT: KEEP (as 300/300 + `keepStaleData=true`)**

- **Hypothesis:** `staleTTL=300` + `setStaleCacheEntriesTTL(300)` extends the
  stale-serving window after backend loss from ~60 s to ~300 s per entry.
- **Round A finding (300/300 alone is NOT enough):** with the raised values
  but default `keepStaleData=false`, the first stale-test (recursor stopped at
  entry-expiry+6 s) showed netflix.com (TTL 60) FAILING immediately while
  unexpired entries served normally, and google.com serving stale only from
  expiry until expiry+31 s, then purged. Source root cause: dnsdist's cache
  maintenance thread purges expired entries every `cacheCleaningDelay` (60 s
  default) *unless* the cache sets `keepStaleData=true` and the pool has all
  backends down (dnsdist.cc cache-maintenance; `shouldKeepStaleData()` in
  dnsdist-backend.cc returns true only when `countServers(true)==0`). The
  stale lookup path itself is fine (`allowExpired = d_staleCacheEntriesTTL`
  when no backend is selected; single-server `firstAvailable` falls through
  `leastOutstanding`, which returns nullptr with all servers down). Practical
  implication: **the stack's previous 60 s stale configuration never delivered
  its 60 s — the effective window was at most one cleaning cycle (observed
  ≤31 s).**
- **Applied change:** `newPacketCache(..., staleTTL=300, keepStaleData=true)`
  + `setStaleCacheEntriesTTL(300)`.
- **Round B test (keepStaleData=true):** entries primed fresh at t0
  (google 300 s / spotify 277 s / apple 900 s / microsoft 3600 s TTL), recursor
  stopped at t0+310 s (10 s after google/spotify expiry), probe loop every
  ~22 s through the window:

  | t | google | spotify | apple | microsoft | uncached probe |
  |---|---|---|---|---|---|
  | +310 | FAIL | 300 (stale) | 588 | 3288 | FAIL |
  | +334 … +555 | 300 (stale) | 300 (stale) | fresh, counting down | fresh, counting down | FAIL |
  | +577 | 300 | FAIL (~285 s stale) | 345 | 3045 | FAIL |
  | +601 | FAIL (~301 s stale) | FAIL | 295 | 2995 | FAIL |

  Stale window = **the full 300 s per entry** (google: stale until 301 s past
  expiry, then FAIL; spotify identical 25 s earlier). During the outage the
  cache answered everything it had; uncached names failed as expected (no
  backend, nothing to serve). Recovery: recursor restarted → uncached names
  resolve again, TTLs restored fresh (google 300, netflix 60).
- **Healthy-path regression check (official harness, warm):**

  | Metric | Official baseline | Anchor | E4 (300/300+keepStale) |
  |---|---|---|---|
  | Warm p50 (ms) | 0.049 | 0.049 | 0.045 |
  | Warm p95 (ms) | 0.093 | 0.101 | 0.105 |
  | Warm p99 (ms) | 0.147 | 0.203 | 0.223 |
  | Warm dnsdist hit % | 99.9 | 100.0 | 99.9 |
  | Queries lost | 0 | 0 | 0 |

  Phase passed; all percentiles inside the same-config noise band observed
  across the battery (warm p99 spanned 0.135–0.223 on configs that measured
  flat-to-better on every other axis).
- **Verdict: KEEP.** Resilience win of 5× (300 s vs ≤31 s effective) with no
  healthy-path regression. The keep includes `keepStaleData=true`, without
  which the staleTTL raise is cosmetic — that interaction is the main finding
  of this experiment. Rollback: restore `staleTTL=60`,
  `setStaleCacheEntriesTTL(60)`, remove `keepStaleData=true`, recreate
  dnsdist.
