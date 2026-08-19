package metrics

import (
	"fmt"
	"io"
	"math"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
	"time"
)

// scrape exercises the real /metrics handler and returns every exposition
// line keyed as "name{labels}" so tests assert exact metric names, labels,
// and values end to end.
func scrape(t *testing.T, m *Metrics) map[string]float64 {
	t.Helper()

	srv := httptest.NewServer(m.Handler())
	defer srv.Close()

	resp, err := http.Get(srv.URL)
	if err != nil {
		t.Fatalf("GET /metrics: %v", err)
	}
	defer resp.Body.Close()

	if ct := resp.Header.Get("Content-Type"); !strings.HasPrefix(ct, "text/plain") {
		t.Fatalf("Content-Type = %q, want text/plain", ct)
	}

	b, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatalf("read body: %v", err)
	}
	body := string(b)

	out := map[string]float64{}
	for _, line := range strings.Split(body, "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		idx := strings.LastIndex(line, " ")
		if idx < 0 {
			t.Fatalf("malformed exposition line: %q", line)
		}
		v, err := strconv.ParseFloat(line[idx+1:], 64)
		if err != nil {
			t.Fatalf("parse value in %q: %v", line, err)
		}
		out[line[:idx]] = v
	}
	return out
}

func TestLatencyBucketsExact(t *testing.T) {
	want := []float64{0.0001, 0.00025, 0.0005, 0.001, 0.0025, 0.005, 0.01}
	if len(LatencyBuckets) != len(want) {
		t.Fatalf("LatencyBuckets = %v, want %v", LatencyBuckets, want)
	}
	for i := range want {
		if LatencyBuckets[i] != want[i] {
			t.Fatalf("LatencyBuckets[%d] = %v, want %v (full: %v)", i, LatencyBuckets[i], want[i], LatencyBuckets)
		}
	}
}

// TestObserveResponseLatencyBuckets pins the exact bucket series a sample
// lands in, including sub-millisecond values that integer-millisecond event
// latency (150µs -> 0 ms) would zero out.
func TestObserveResponseLatencyBuckets(t *testing.T) {
	m := New()

	m.ObserveResponseLatency(false, 150*time.Microsecond)  // 0.15 ms
	m.ObserveResponseLatency(false, 250*time.Microsecond)  // exactly on the 0.00025 le boundary
	m.ObserveResponseLatency(false, 3*time.Millisecond)    // above 0.0025, below 0.005
	m.ObserveResponseLatency(false, 25*time.Millisecond)   // over the last bucket -> +Inf

	got := scrape(t, m)

	type bucketCase struct {
		le    string
		count float64
	}
	cases := []bucketCase{
		{"0.0001", 0},  // 150µs and 250µs exceed it
		{"0.00025", 2}, // 150µs, and 250µs exactly on the boundary (le is inclusive)
		{"0.0005", 2},
		{"0.001", 2},
		{"0.0025", 2},
		{"0.005", 3}, // 3ms counts here
		{"0.01", 3},
		{"+Inf", 4}, // 25ms overflows the last finite bucket
	}
	for _, tc := range cases {
		key := fmt.Sprintf(`dnstap_processor_response_latency_seconds_bucket{prober="false",le="%s"}`, tc.le)
		if v, ok := got[key]; !ok {
			t.Errorf("missing series %s", key)
		} else if v != tc.count {
			t.Errorf("%s = %v, want %v", key, v, tc.count)
		}
	}

	wantSum := (150*time.Microsecond + 250*time.Microsecond + 3*time.Millisecond + 25*time.Millisecond).Seconds()
	if v := got[`dnstap_processor_response_latency_seconds_sum{prober="false"}`]; math.Abs(v-wantSum) > 1e-12 {
		t.Errorf("sum = %v, want %v", v, wantSum)
	}
	if v := got[`dnstap_processor_response_latency_seconds_count{prober="false"}`]; v != 4 {
		t.Errorf("count = %v, want 4", v)
	}
}

// TestProberSamplesCannotEnterProductionSeries proves that observations
// classified as prober traffic land only in the prober="true" series: the
// prober sample (500µs) would bump the production le="0.0005" bucket from 1
// to 2 if it leaked.
func TestProberSamplesCannotEnterProductionSeries(t *testing.T) {
	m := New()

	m.ObserveResponseLatency(false, 200*time.Microsecond) // production
	m.ObserveResponseLatency(false, 3*time.Millisecond)   // production
	m.ObserveResponseLatency(true, 500*time.Microsecond)  // prober

	got := scrape(t, m)

	// Production series: exactly the two production samples.
	prod := map[string]float64{
		`dnstap_processor_response_latency_seconds_bucket{prober="false",le="0.0001"}`: 0,
		`dnstap_processor_response_latency_seconds_bucket{prober="false",le="0.00025"}`: 1,
		`dnstap_processor_response_latency_seconds_bucket{prober="false",le="0.0005"}`:  1, // prober 500µs must NOT land here
		`dnstap_processor_response_latency_seconds_bucket{prober="false",le="0.001"}`:   1,
		`dnstap_processor_response_latency_seconds_bucket{prober="false",le="0.0025"}`:  1,
		`dnstap_processor_response_latency_seconds_bucket{prober="false",le="0.005"}`:   2,
		`dnstap_processor_response_latency_seconds_bucket{prober="false",le="0.01"}`:    2,
		`dnstap_processor_response_latency_seconds_bucket{prober="false",le="+Inf"}`:    2,
		`dnstap_processor_response_latency_seconds_count{prober="false"}`:               2,
	}
	for key, want := range prod {
		if v, ok := got[key]; !ok {
			t.Errorf("missing series %s", key)
		} else if v != want {
			t.Errorf("%s = %v, want %v (prober sample leaked into production series?)", key, v, want)
		}
	}

	// Prober series: exactly the one prober sample.
	prb := map[string]float64{
		`dnstap_processor_response_latency_seconds_bucket{prober="true",le="0.0001"}`:  0,
		`dnstap_processor_response_latency_seconds_bucket{prober="true",le="0.00025"}`: 0,
		`dnstap_processor_response_latency_seconds_bucket{prober="true",le="0.0005"}`:  1,
		`dnstap_processor_response_latency_seconds_bucket{prober="true",le="0.001"}`:   1,
		`dnstap_processor_response_latency_seconds_bucket{prober="true",le="0.0025"}`:  1,
		`dnstap_processor_response_latency_seconds_bucket{prober="true",le="0.005"}`:   1,
		`dnstap_processor_response_latency_seconds_bucket{prober="true",le="0.01"}`:    1,
		`dnstap_processor_response_latency_seconds_bucket{prober="true",le="+Inf"}`:    1,
		`dnstap_processor_response_latency_seconds_count{prober="true"}`:               1,
	}
	for key, want := range prb {
		if v, ok := got[key]; !ok {
			t.Errorf("missing series %s", key)
		} else if v != want {
			t.Errorf("%s = %v, want %v", key, v, want)
		}
	}
}

// TestObserveResponseLatencyIgnoresInvalid guards the observation path
// against missing/inverted timestamps contributing bogus zero observations.
func TestObserveResponseLatencyIgnoresInvalid(t *testing.T) {
	m := New()

	m.ObserveResponseLatency(false, 0)
	m.ObserveResponseLatency(false, -5*time.Millisecond)
	m.ObserveResponseLatency(true, 0)

	got := scrape(t, m)
	for key, v := range got {
		if strings.HasPrefix(key, "dnstap_processor_response_latency_seconds") && v != 0 {
			t.Errorf("%s = %v, want 0 (invalid durations must not be observed)", key, v)
		}
	}
}

// TestCounterAndGaugeNamesExposed pins the exact counter/gauge metric names
// exported for pipeline accounting.
func TestCounterAndGaugeNamesExposed(t *testing.T) {
	m := New()

	m.EventsReceived.Inc()
	m.EventsBuffered.Add(3)
	m.EventsShipped.Add(2)
	m.EventsDropped.Inc()
	m.BufferPending.Set(7)

	got := scrape(t, m)

	want := map[string]float64{
		"dnstap_processor_events_received_total": 1,
		"dnstap_processor_events_buffered_total": 3,
		"dnstap_processor_events_shipped_total":  2,
		"dnstap_processor_events_dropped_total":   1,
		"dnstap_processor_buffer_pending":         7,
	}
	for name, wantV := range want {
		if v, ok := got[name]; !ok {
			t.Errorf("missing metric %s", name)
		} else if v != wantV {
			t.Errorf("%s = %v, want %v", name, v, wantV)
		}
	}
}
