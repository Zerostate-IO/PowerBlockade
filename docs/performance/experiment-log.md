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

## E2 — ECS off at the edge

- **Hypothesis:** `useClientSubnet=false` stops dnsdist appending ECS options
  on upstream queries. /24-truncated ECS keys mean single-subnet clients share
  packet-cache keys anyway, so the edge hit ratio should not move (overhead
  removal only, small win possible).
- **Change / numbers / verdict:** filled after measurement.

---

## E3 — `refresh-on-ttl-perc=10` (recursor)

- **Hypothesis:** near-expiry record/packet-cache entries get background
  refresh tasks, so future queries never wait on an expired entry.
- **Shielding caveat:** behind a ~99.9% edge, only a trickle of queries reach
  the recursor; refresh opportunities are correspondingly rare. "No measurable
  benefit behind dnsdist" is an acceptable outcome.
- **Verification plan:** setting accepted (recursor logs / `rec_control get
  refresh-on-ttl-perc` if exposed); signal = `all-outqueries` delta without
  matching cache-miss delta during steady corpus load.
- **Change / numbers / verdict:** filled after measurement.

---

## E4 — Stale depth 60/60 → 300/300

- **Hypothesis:** `staleTTL=300` + `setStaleCacheEntriesTTL(300)` extends the
  stale-serving window after backend loss from ~60 s to ~300 s per entry.
- **Test design:** recursor stopped → repeated `dig` of previously cached
  domains through the edge → stale answers (decrementing TTLs) must continue
  for up to ~300 s past expiry; error rate sampled over the outage window;
  recursor restarted → fresh answers with restored TTLs (refreshed);
  warm-mode benchmark afterwards proves no healthy-path regression.
- **Change / numbers / verdict:** filled after measurement.
