package main

import (
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/dnstap/golang-dnstap"
	"github.com/miekg/dns"

	"github.com/powerblockade/dnstap-processor/internal/buffer"
	"github.com/powerblockade/dnstap-processor/internal/metrics"
)

// clientResponseMessage builds a complete dnstap CLIENT_RESPONSE frame for
// clientIP carrying a packed NOERROR A-question response and a
// query_time/response_time pair d apart (mirrors what dnsdist sends).
func clientResponseMessage(t *testing.T, clientIP string, d time.Duration) *dnstap.Message {
	t.Helper()

	base := time.Unix(1_700_000_000, 0)
	qts := base
	rts := base.Add(d)

	reply := new(dns.Msg)
	reply.SetReply(&dns.Msg{
		Question: []dns.Question{{Name: "probe.example.com.", Qtype: dns.TypeA, Qclass: dns.ClassINET}},
	})
	wire, err := reply.Pack()
	if err != nil {
		t.Fatalf("pack dns response: %v", err)
	}

	mt := dnstap.Message_CLIENT_RESPONSE
	qSec := uint64(qts.Unix())
	qNsec := uint32(qts.Nanosecond())
	rSec := uint64(rts.Unix())
	rNsec := uint32(rts.Nanosecond())
	qPort := uint32(5353)
	return &dnstap.Message{
		Type:             &mt,
		QueryAddress:     net.ParseIP(clientIP).To4(),
		QueryPort:        &qPort,
		QueryTimeSec:     &qSec,
		QueryTimeNsec:    &qNsec,
		ResponseTimeSec:  &rSec,
		ResponseTimeNsec: &rNsec,
		ResponseMessage:  wire,
	}
}

// newTestProcessor wires a responseProcessor with a passthrough makeEvent
// (no RPZ/internal lookups) so tests assert exactly the fields process()
// derives from the frame.
func newTestProcessor(m *metrics.Metrics, dropProberEvents bool) responseProcessor {
	return responseProcessor{
		probers:          parseProberIPs("172.30.0.30"),
		dropProberEvents: dropProberEvents,
		mets:             m,
		makeEvent: func(ts time.Time, clientIP string, qname string, qtype int, rcode int, latencyMS int) buffer.Event {
			return buffer.Event{
				Ts:        ts.Format(time.RFC3339Nano),
				ClientIP:  clientIP,
				QName:     qname,
				QType:     qtype,
				RCode:     rcode,
				LatencyMS: latencyMS,
			}
		},
	}
}

// scrape exercises the real /metrics handler and returns every exposition
// line keyed as "name{labels}" (same pattern as internal/metrics tests) so
// assertions cover exact series names, labels, and values.
func scrape(t *testing.T, m *metrics.Metrics) map[string]float64 {
	t.Helper()

	srv := httptest.NewServer(m.Handler())
	defer srv.Close()

	resp, err := http.Get(srv.URL)
	if err != nil {
		t.Fatalf("GET /metrics: %v", err)
	}
	defer resp.Body.Close()

	b, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatalf("read body: %v", err)
	}

	out := map[string]float64{}
	for _, line := range strings.Split(string(b), "\n") {
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

func countKey(prober string) string {
	return fmt.Sprintf(`dnstap_processor_response_latency_seconds_count{prober=%q}`, prober)
}

// TestProberEventDroppedButMetricsObserved is the core DROP_PROBER_EVENTS
// contract: with the flag on, a prober-source event is NOT shipped, yet its
// latency lands on the prober="true" series, the production series stays
// empty, and events_dropped_total stays untouched (intentional suppression
// is not a loss).
func TestProberEventDroppedButMetricsObserved(t *testing.T) {
	m := metrics.New()
	proc := newTestProcessor(m, true)

	// The main loop counts every received frame before decoding.
	m.EventsReceived.Inc()

	ev, ok := proc.process(clientResponseMessage(t, "172.30.0.30", 1500*time.Microsecond))
	if ok {
		t.Fatalf("process() shipped prober event (%+v), want suppressed", ev)
	}

	got := scrape(t, m)
	if v := got[countKey(metrics.ProberLabelTrue)]; v != 1 {
		t.Errorf("%s = %v, want 1 (metrics must be observed despite the drop)", countKey(metrics.ProberLabelTrue), v)
	}
	if v := got[countKey(metrics.ProberLabelFalse)]; v != 0 {
		t.Errorf("%s = %v, want 0 (prober sample leaked into production series)", countKey(metrics.ProberLabelFalse), v)
	}
	if v := got["dnstap_processor_events_received_total"]; v != 1 {
		t.Errorf("dnstap_processor_events_received_total = %v, want 1 (suppressed frames are still received)", v)
	}
	if v := got["dnstap_processor_events_dropped_total"]; v != 0 {
		t.Errorf("dnstap_processor_events_dropped_total = %v, want 0 (suppression is not a loss; the drop signal is received outpacing shipped)", v)
	}
	if v := got["dnstap_processor_events_shipped_total"]; v != 0 {
		t.Errorf("dnstap_processor_events_shipped_total = %v, want 0", v)
	}
}

// TestProberEventShippedWhenFlagOff pins the opt-out: with the flag off, a
// prober-source event ships exactly like today, and its metrics still land
// on the prober series only.
func TestProberEventShippedWhenFlagOff(t *testing.T) {
	m := metrics.New()
	proc := newTestProcessor(m, false)

	ev, ok := proc.process(clientResponseMessage(t, "172.30.0.30", 1500*time.Microsecond))
	if !ok {
		t.Fatalf("process() ok = false, want shipped")
	}
	if ev.ClientIP != "172.30.0.30" {
		t.Errorf("ClientIP = %q, want 172.30.0.30", ev.ClientIP)
	}
	if ev.QName != "probe.example.com." {
		t.Errorf("QName = %q, want probe.example.com.", ev.QName)
	}
	if ev.LatencyMS != 1 { // 1500µs keeps its historic coarse truncation
		t.Errorf("LatencyMS = %d, want 1", ev.LatencyMS)
	}

	got := scrape(t, m)
	if v := got[countKey(metrics.ProberLabelTrue)]; v != 1 {
		t.Errorf("%s = %v, want 1", countKey(metrics.ProberLabelTrue), v)
	}
	if v := got[countKey(metrics.ProberLabelFalse)]; v != 0 {
		t.Errorf("%s = %v, want 0", countKey(metrics.ProberLabelFalse), v)
	}
}

// TestNonProberUnaffectedByDropFlag covers production traffic in both
// modes: a non-prober source ships and observes on the prober="false"
// series whether the flag is on or off.
func TestNonProberUnaffectedByDropFlag(t *testing.T) {
	for _, drop := range []bool{true, false} {
		t.Run(fmt.Sprintf("drop=%v", drop), func(t *testing.T) {
			m := metrics.New()
			proc := newTestProcessor(m, drop)

			ev, ok := proc.process(clientResponseMessage(t, "192.168.1.10", 3*time.Millisecond))
			if !ok {
				t.Fatalf("process() ok = false, want shipped (non-prober must never be dropped)")
			}
			if ev.ClientIP != "192.168.1.10" {
				t.Errorf("ClientIP = %q, want 192.168.1.10", ev.ClientIP)
			}

			got := scrape(t, m)
			if v := got[countKey(metrics.ProberLabelFalse)]; v != 1 {
				t.Errorf("%s = %v, want 1", countKey(metrics.ProberLabelFalse), v)
			}
			if v := got[countKey(metrics.ProberLabelTrue)]; v != 0 {
				t.Errorf("%s = %v, want 0", countKey(metrics.ProberLabelTrue), v)
			}
		})
	}
}

// TestUnparseableFramesNeverShip guards the no-event paths shared by both
// modes: non-CLIENT_RESPONSE types and responses without a query address
// observe nothing and ship nothing.
func TestUnparseableFramesNeverShip(t *testing.T) {
	for _, drop := range []bool{true, false} {
		t.Run(fmt.Sprintf("drop=%v", drop), func(t *testing.T) {
			m := metrics.New()
			proc := newTestProcessor(m, drop)

			mt := dnstap.Message_CLIENT_QUERY
			if ev, ok := proc.process(&dnstap.Message{Type: &mt}); ok {
				t.Errorf("process(CLIENT_QUERY) = (%+v, true), want no ship", ev)
			}
			if ev, ok := proc.process(&dnstap.Message{}); ok {
				t.Errorf("process(empty message) = (%+v, true), want no ship", ev)
			}

			got := scrape(t, m)
			for key, v := range got {
				if strings.HasPrefix(key, "dnstap_processor_response_latency_seconds") && v != 0 {
					t.Errorf("%s = %v, want 0 (no observation from unparseable frames)", key, v)
				}
			}
		})
	}
}
