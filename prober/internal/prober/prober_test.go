package prober

import (
	"fmt"
	"net"
	"testing"
	"time"

	"github.com/miekg/dns"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/testutil"
	dto "github.com/prometheus/client_model/go"
)

// fakeDNS is an in-process UDP DNS server for tests. It answers A queries
// from a fixed set of names, refuses a fixed set, and can be told to stay
// silent (black hole mode) to produce client timeouts. All configuration is
// supplied before the server goroutine starts; tests must not mutate it
// afterwards (the handler reads it concurrently).
type fakeDNS struct {
	udp    *dns.Server
	addr   string
	answer map[string]bool // name -> answer normally; false = REFUSED
	silent bool
}

func newFakeDNS(t *testing.T, answer map[string]bool, silent bool) *fakeDNS {
	t.Helper()
	f := &fakeDNS{answer: answer, silent: silent}
	pc, err := net.ListenPacket("udp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	f.addr = pc.LocalAddr().String()
	f.udp = &dns.Server{
		PacketConn: pc,
		Handler: dns.HandlerFunc(func(w dns.ResponseWriter, r *dns.Msg) {
			if f.silent {
				return // never reply: client times out
			}
			m := new(dns.Msg)
			m.SetReply(r)
			q := r.Question[0]
			allowed, known := f.answer[q.Name]
			switch {
			case !known:
				m.Rcode = dns.RcodeNameError
			case !allowed:
				m.Rcode = dns.RcodeRefused
			case q.Qtype == dns.TypeA:
				rr, _ := dns.NewRR(fmt.Sprintf("%s 60 IN A 192.0.2.1", q.Name))
				m.Answer = append(m.Answer, rr)
			}
			_ = w.WriteMsg(m)
		}),
	}
	go func() { _ = f.udp.ActivateAndServe() }()
	t.Cleanup(func() { _ = f.udp.Shutdown() })
	return f
}

// metricsSnapshot reads the counters the tests assert on.
func metricsSnapshot() map[string]float64 {
	return map[string]float64{
		"sent":      testutil.ToFloat64(queriesSent),
		"answered":  testutil.ToFloat64(queriesAnswered),
		"refused":   testutil.ToFloat64(queriesRefused),
		"timed_out": testutil.ToFloat64(queriesTimedOut),
		"errored":   testutil.ToFloat64(queriesErrored),
	}
}

// sampleCount returns the number of observations recorded in h. Histograms
// have no single float value, so testutil.ToFloat64 panics on them.
func sampleCount(t *testing.T, h prometheus.Histogram) uint64 {
	t.Helper()
	var m dto.Metric
	if err := h.Write(&m); err != nil {
		t.Fatalf("write histogram: %v", err)
	}
	return m.GetHistogram().GetSampleCount()
}

func newTestProber(addr string) *Prober {
	return New(addr, 250*time.Millisecond)
}

func TestQueryAnsweredAndRefusedAndHistogram(t *testing.T) {
	f := newFakeDNS(t, map[string]bool{"ok.example.": true, "refused.example.": false}, false)

	p := newTestProber(f.addr)
	defer p.Close()

	// Metrics are package-level and accumulate across tests; every test
	// asserts deltas against a snapshot taken up front.
	before := metricsSnapshot()
	beforeObs := sampleCount(t, queryLatency)

	res, latency := p.Query("ok.example", dns.TypeA)
	if res != ResultAnswered {
		t.Fatalf("result = %v, want ResultAnswered", res)
	}
	if latency <= 0 {
		t.Fatalf("latency = %v, want > 0", latency)
	}

	res, _ = p.Query("refused.example", dns.TypeA)
	if res != ResultRefused {
		t.Fatalf("result = %v, want ResultRefused", res)
	}

	got := metricsSnapshot()
	want := map[string]float64{"sent": 2, "answered": 2, "refused": 1, "timed_out": 0, "errored": 0}
	for k, v := range want {
		if got[k]-before[k] != v {
			t.Errorf("%s delta = %v, want %v", k, got[k]-before[k], v)
		}
	}

	// Both responses land in the latency histogram (REFUSED included: the
	// server was reachable, the client observed real latency).
	if n := sampleCount(t, queryLatency) - beforeObs; n != 2 {
		t.Fatalf("histogram observations delta = %d, want 2", n)
	}
}

func TestQueryTimeoutNeverRetried(t *testing.T) {
	f := newFakeDNS(t, map[string]bool{"slow.example.": true}, true) // server accepts packets, never answers

	p := newTestProber(f.addr)
	defer p.Close()

	before := metricsSnapshot()

	start := time.Now()
	res, latency := p.Query("slow.example", dns.TypeA)
	elapsed := time.Since(start)
	if res != ResultTimedOut {
		t.Fatalf("result = %v, want ResultTimedOut", res)
	}
	if latency < 200*time.Millisecond {
		t.Errorf("latency = %v, want >= timeout (250ms)", latency)
	}
	// No retry: the single query must not exceed ~1.5x the timeout.
	if elapsed > 400*time.Millisecond {
		t.Errorf("elapsed = %v, want < 400ms (no second send)", elapsed)
	}

	got := metricsSnapshot()
	if got["timed_out"]-before["timed_out"] != 1 || got["sent"]-before["sent"] != 1 || got["answered"]-before["answered"] != 0 {
		t.Fatalf("counters delta = %v (from %v), want sent=1 timed_out=1 answered=0", got, before)
	}
}

func TestQueryErrorUnreachableServer(t *testing.T) {
	// Bind then close to find a port that refuses packets quickly.
	pc, err := net.ListenPacket("udp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	addr := pc.LocalAddr().String()
	pc.Close()

	p := New(addr, 250*time.Millisecond)
	defer p.Close()

	// UDP to a closed port usually yields ICMP port unreachable surfaced as
	// connection refused on Linux; on hosts that blackhole it, this is a
	// timeout. Both are acceptable outcomes; assert classification matches.
	before := metricsSnapshot()
	res, _ := p.Query("any.example", dns.TypeA)
	if res != ResultErrored && res != ResultTimedOut {
		t.Fatalf("result = %v, want ResultErrored or ResultTimedOut", res)
	}
	got := metricsSnapshot()
	if got["errored"]-before["errored"]+got["timed_out"]-before["timed_out"] != 1 {
		t.Fatalf("counters delta = %v (from %v), want exactly one failure counted", got, before)
	}
}

func TestQueryReusesWarmSocket(t *testing.T) {
	f := newFakeDNS(t, map[string]bool{"warm.example.": true}, false)

	p := newTestProber(f.addr)
	defer p.Close()

	for i := 0; i < 3; i++ {
		if res, _ := p.Query("warm.example", dns.TypeA); res != ResultAnswered {
			t.Fatalf("query %d result = %v, want ResultAnswered", i, res)
		}
	}
	if p.conn == nil {
		t.Fatal("persistent socket not retained after successful query")
	}
}

func TestHistogramBucketsMatchProcessor(t *testing.T) {
	want := []float64{0.0001, 0.00025, 0.0005, 0.001, 0.0025, 0.005, 0.01}
	if len(LatencyBuckets) != len(want) {
		t.Fatalf("bucket count = %d, want %d", len(LatencyBuckets), len(want))
	}
	for i := range want {
		if LatencyBuckets[i] != want[i] {
			t.Errorf("bucket %d = %v, want %v", i, LatencyBuckets[i], want[i])
		}
	}
}

func TestHistogramObservesSubMillisecond(t *testing.T) {
	f := newFakeDNS(t, map[string]bool{"fast.example.": true}, false)

	p := newTestProber(f.addr)
	defer p.Close()

	before := sampleCount(t, queryLatency)
	res, latency := p.Query("fast.example", dns.TypeA)
	if res != ResultAnswered {
		t.Fatalf("result = %v, want ResultAnswered", res)
	}
	after := sampleCount(t, queryLatency)
	if after != before+1 {
		t.Fatalf("histogram observations = %d, want %d", after, before+1)
	}
	// Loopback latency must be far below the coarsest bucket pair to prove
	// sub-millisecond durations are recorded (bucket 0.001 covers ≤1ms).
	if latency >= time.Millisecond {
		t.Fatalf("loopback latency = %v, want < 1ms", latency)
	}
}

func TestJitterSleepBounds(t *testing.T) {
	p := New("127.0.0.1:53", time.Second)
	defer p.Close()

	// Vars, not consts: the ±10% bounds are fractional in float64 (1.1 is
	// not binary-exact), and constant float→Duration conversions with a
	// fractional value do not compile. Runtime conversion truncates exactly
	// like JitterSleep does, so the bounds stay tight.
	interval := 60 * time.Second
	jitterPct := 10.0
	lo := time.Duration(float64(interval) * (1 - jitterPct/100))
	hi := time.Duration(float64(interval) * (1 + jitterPct/100))

	belowLo, aboveHi := 0, 0
	for i := 0; i < 10000; i++ {
		d := p.JitterSleep(interval, jitterPct)
		if d < lo {
			belowLo++
		}
		if d > hi {
			aboveHi++
		}
		if d < 0 {
			t.Fatalf("negative sleep %v", d)
		}
	}
	if belowLo > 0 || aboveHi > 0 {
		t.Fatalf("jitter out of bounds: %d below %v, %d above %v", belowLo, lo, aboveHi, hi)
	}
}

func TestJitterSleepZeroJitter(t *testing.T) {
	p := New("127.0.0.1:53", time.Second)
	defer p.Close()

	for i := 0; i < 100; i++ {
		if d := p.JitterSleep(60*time.Second, 0); d != 60*time.Second {
			t.Fatalf("sleep = %v, want exactly interval when jitter disabled", d)
		}
	}
}

func TestObservePass(t *testing.T) {
	ObservePass(2*time.Second, 120)
	if d := testutil.ToFloat64(passDuration); d != 2.0 {
		t.Errorf("pass_duration = %v, want 2", d)
	}
	if n := testutil.ToFloat64(passQueries); n != 120 {
		t.Errorf("pass_queries = %v, want 120", n)
	}
}
