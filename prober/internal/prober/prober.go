// Package prober sends the control corpus to a DNS edge and records
// client-observed latency. This is the ground-truth warm-path signal,
// deliberately separate from production traffic metrics: no retries, no
// per-domain aggregation, no admin-ui integration.
package prober

import (
	"math/rand"
	"net"
	"time"

	"github.com/miekg/dns"
	"github.com/prometheus/client_golang/prometheus"
)

// LatencyBuckets match the dnstap-processor's latency histogram boundaries
// so dashboards can overlay client-observed and server-observed latency on
// the same axes. Values are seconds.
var LatencyBuckets = []float64{0.0001, 0.00025, 0.0005, 0.001, 0.0025, 0.005, 0.01}

var (
	queriesSent = prometheus.NewCounter(prometheus.CounterOpts{
		Name: "powerblockade_prober_queries_sent_total",
		Help: "Control-corpus queries sent to the DNS edge.",
	})
	queriesAnswered = prometheus.NewCounter(prometheus.CounterOpts{
		Name: "powerblockade_prober_queries_answered_total",
		Help: "Control-corpus queries that received a DNS response (any rcode).",
	})
	queriesRefused = prometheus.NewCounter(prometheus.CounterOpts{
		Name: "powerblockade_prober_queries_refused_total",
		Help: "Control-corpus queries answered with REFUSED.",
	})
	queriesTimedOut = prometheus.NewCounter(prometheus.CounterOpts{
		Name: "powerblockade_prober_queries_timed_out_total",
		Help: "Control-corpus queries that exceeded PROBE_TIMEOUT. Never retried.",
	})
	queriesErrored = prometheus.NewCounter(prometheus.CounterOpts{
		Name: "powerblockade_prober_queries_errored_total",
		Help: "Control-corpus queries that failed with a transport error other than a timeout.",
	})
	queryLatency = prometheus.NewHistogram(prometheus.HistogramOpts{
		Name:    "powerblockade_prober_query_latency_seconds",
		Help:    "Client-observed latency of control-corpus queries, from send to response.",
		Buckets: LatencyBuckets,
	})
	passDuration = prometheus.NewGauge(prometheus.GaugeOpts{
		Name: "powerblockade_prober_pass_duration_seconds",
		Help: "Duration of the most recent full pass over the control corpus.",
	})
	passQueries = prometheus.NewGauge(prometheus.GaugeOpts{
		Name: "powerblockade_prober_pass_queries",
		Help: "Number of queries in the most recent pass over the control corpus.",
	})
)

// Registry is the prometheus registry exposing the prober's metrics; it is
// deliberately separate from the default registry so only prober metrics
// are exposed.
var Registry = prometheus.NewRegistry()

func init() {
	Registry.MustRegister(
		queriesSent,
		queriesAnswered,
		queriesRefused,
		queriesTimedOut,
		queriesErrored,
		queryLatency,
		passDuration,
		passQueries,
	)
}

// Result classifies the outcome of one probe.
type Result int

const (
	ResultAnswered Result = iota
	ResultRefused
	ResultTimedOut
	ResultErrored
)

// Prober owns the UDP socket and walks the corpus.
type Prober struct {
	target  string
	timeout time.Duration
	client  *dns.Client
	conn    *dns.Conn
	rand    *rand.Rand
}

// New creates a prober for target ("host:port"). The UDP socket is dialed on
// first use and kept across queries so the client-side path under test is
// warm, matching steady-state production traffic.
func New(target string, timeout time.Duration) *Prober {
	return &Prober{
		target:  target,
		timeout: timeout,
		client: &dns.Client{
			Net:     "udp",
			Timeout: timeout,
			Dialer:  &net.Dialer{Timeout: timeout},
		},
		rand: rand.New(rand.NewSource(time.Now().UnixNano())),
	}
}

// Query sends one DNS query for name/qtype and reports how it ended plus the
// client-observed latency. The query is sent exactly once: a timeout counts
// as a timeout, a transport error as an error; there are no retries.
func (p *Prober) Query(name string, qtype uint16) (Result, time.Duration) {
	m := new(dns.Msg)
	m.SetQuestion(dns.Fqdn(name), qtype)
	m.RecursionDesired = true

	start := time.Now()
	resp, err := p.exchange(m)
	latency := time.Since(start)

	queriesSent.Inc()
	if err != nil {
		if isTimeout(err) {
			queriesTimedOut.Inc()
			return ResultTimedOut, latency
		}
		queriesErrored.Inc()
		return ResultErrored, latency
	}

	queriesAnswered.Inc()
	queryLatency.Observe(latency.Seconds())
	if resp.Rcode == dns.RcodeRefused {
		queriesRefused.Inc()
		return ResultRefused, latency
	}
	return ResultAnswered, latency
}

// exchange sends m over the persistent connected UDP socket. On any error
// the socket is dropped (it may be wedged or unreachable); the next query
// dials a fresh one. The failed query itself is never resent.
func (p *Prober) exchange(m *dns.Msg) (*dns.Msg, error) {
	if p.conn == nil {
		conn, err := p.client.Dial(p.target)
		if err != nil {
			return nil, err
		}
		p.conn = conn
	}
	resp, _, err := p.client.ExchangeWithConn(m, p.conn)
	if err != nil {
		p.conn.Close()
		p.conn = nil
		return nil, err
	}
	return resp, nil
}

func isTimeout(err error) bool {
	if ne, ok := err.(net.Error); ok {
		return ne.Timeout()
	}
	return false
}

// JitterSleep returns how long to wait before the next pass: interval scaled
// by a uniformly random factor in [-jitterPct%, +jitterPct%]. With the
// defaults (60s, ±10%) the result is between 54s and 66s. The result is
// clamped at zero, never negative.
func (p *Prober) JitterSleep(interval time.Duration, jitterPct float64) time.Duration {
	if jitterPct <= 0 || interval <= 0 {
		return interval
	}
	factor := 1 + (p.rand.Float64()*2-1)*(jitterPct/100)
	if factor < 0 {
		factor = 0
	}
	return time.Duration(float64(interval) * factor)
}

// ObservePass records the duration and size of a completed corpus pass.
func ObservePass(d time.Duration, queries int) {
	passDuration.Set(d.Seconds())
	passQueries.Set(float64(queries))
}

// Close releases the persistent socket, if any.
func (p *Prober) Close() error {
	if p.conn != nil {
		err := p.conn.Close()
		p.conn = nil
		return err
	}
	return nil
}
