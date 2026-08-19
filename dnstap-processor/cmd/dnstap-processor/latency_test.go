package main

import (
	"testing"
	"time"

	"github.com/dnstap/golang-dnstap"
)

// dnstapMessageWithTimes builds a CLIENT_RESPONSE message with the given
// query/response timestamps (response_time defaults to query_time + d).
func dnstapMessageWithTimes(querySec uint64, queryNsec uint32, respSec uint64, respNsec uint32) *dnstap.Message {
	mt := dnstap.Message_CLIENT_RESPONSE
	return &dnstap.Message{
		Type:             &mt,
		QueryTimeSec:     &querySec,
		QueryTimeNsec:    &queryNsec,
		ResponseTimeSec:  &respSec,
		ResponseTimeNsec: &respNsec,
	}
}

func latencyMessage(d time.Duration) *dnstap.Message {
	base := time.Unix(1_700_000_000, 0)
	q := base
	r := base.Add(d)
	return dnstapMessageWithTimes(
		uint64(q.Unix()), uint32(q.Nanosecond()),
		uint64(r.Unix()), uint32(r.Nanosecond()),
	)
}

func TestDnstapLatencyPreservesSubMillisecond(t *testing.T) {
	// Every case here is zeroed by integer-millisecond conversion
	// (int(d/time.Millisecond) == 0); the duration must survive at full
	// precision for the histogram observation.
	cases := []struct {
		name string
		d    time.Duration
	}{
		{"1 microsecond", 1 * time.Microsecond},
		{"150 microseconds", 150 * time.Microsecond},
		{"250 microseconds", 250 * time.Microsecond},
		{"999998 nanoseconds", 999998 * time.Nanosecond},
		{"1.5 milliseconds", 1500 * time.Microsecond},
		{"3.7 milliseconds", 3*time.Millisecond + 700*time.Microsecond},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			d, ok := dnstapLatency(latencyMessage(tc.d))
			if !ok {
				t.Fatalf("dnstapLatency() ok = false, want true")
			}
			if d != tc.d {
				t.Errorf("dnstapLatency() = %v, want %v (precision lost)", d, tc.d)
			}
			// The coarse event field keeps its historic truncation.
			if ms := int(d / time.Millisecond); ms != int(tc.d/time.Millisecond) {
				t.Errorf("int(d/time.Millisecond) = %d, want %d", ms, int(tc.d/time.Millisecond))
			}
		})
	}
}

func TestDnstapLatencyInvalidTimestamps(t *testing.T) {
	cases := []struct {
		name string
		msg  *dnstap.Message
	}{
		{"missing query time", dnstapMessageWithTimes(0, 0, 1_700_000_000, 0)},
		{"missing response time", dnstapMessageWithTimes(1_700_000_000, 0, 0, 0)},
		{"response before query", latencyMessage(-3 * time.Millisecond)},
		{"zero duration", latencyMessage(0)},
		{"nil message", nil},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			d, ok := dnstapLatency(tc.msg)
			if ok {
				t.Fatalf("dnstapLatency() ok = true, want false")
			}
			if d != 0 {
				t.Errorf("dnstapLatency() = %v, want 0", d)
			}
		})
	}
}

func TestParseProberIPs(t *testing.T) {
	p := parseProberIPs(" 172.30.0.30 , 10.0.0.5 ,, ")
	if !p.contains("172.30.0.30") {
		t.Errorf("contains(172.30.0.30) = false, want true")
	}
	if !p.contains("10.0.0.5") {
		t.Errorf("contains(10.0.0.5) = false, want true")
	}
	if p.contains("172.30.0.31") {
		t.Errorf("contains(172.30.0.31) = true, want false")
	}

	if got := parseProberIPs(""); len(got) != 0 {
		t.Errorf("parseProberIPs(\"\") = %v, want empty", got)
	}
	if got := parseProberIPs(" , ,"); len(got) != 0 {
		t.Errorf("parseProberIPs(\" , ,\") = %v, want empty", got)
	}
}

// TestProberClassificationBeforeObservation documents the classification
// contract: exactly the configured dnstap query source addresses are
// probers, and every other address — including neighbours in the same
// subnet — stays on production series.
func TestProberClassificationBeforeObservation(t *testing.T) {
	p := parseProberIPs("172.30.0.30")

	if !p.contains("172.30.0.30") {
		t.Fatalf("prober IP must be classified as prober")
	}
	for _, ip := range []string{"172.30.0.29", "172.30.0.31", "192.168.1.10", ""} {
		if p.contains(ip) {
			t.Errorf("contains(%q) = true, want false", ip)
		}
	}
}
