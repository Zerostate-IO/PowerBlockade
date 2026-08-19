package main

import (
	"net"
	"time"

	"github.com/dnstap/golang-dnstap"
	"github.com/miekg/dns"

	"github.com/powerblockade/dnstap-processor/internal/buffer"
	"github.com/powerblockade/dnstap-processor/internal/metrics"
)

// responseProcessor turns one decoded dnstap CLIENT_RESPONSE frame into a
// shippable buffer.Event. It owns the ordering contract between metrics and
// the ship decision:
//
//  1. classify the dnstap query source IP as prober or production,
//  2. observe the edge-latency histogram on the matching prober series,
//  3. only then decide whether the event is enqueued for shipping.
//
// When DROP_PROBER_EVENTS is on (the default), prober-source events are
// suppressed at step 3: the synthetic prober's events are worthless as
// stored logs (the prober IP sits in INTERNAL_SUBNETS and is already
// excluded from analytics) and would add millions of rows per day, yet its
// full metrics value is preserved because observation already happened.
//
// Counter semantics for a suppressed event: events_received_total counted
// the frame when it arrived (the main loop increments it before decoding),
// and the latency histogram keeps its prober="true" sample. Nothing else is
// touched — in particular events_dropped_total stays unchanged, because it
// counts *losses* (backpressure, buffer write failure), not intentional
// suppression. An operator sees the drop as events_received_total (plus the
// prober="true" histogram count) outpacing events_shipped_total; that
// divergence is the drop signal and needs no dedicated counter.
type responseProcessor struct {
	probers proberIPs
	// dropProberEvents mirrors DROP_PROBER_EVENTS (default true).
	dropProberEvents bool
	mets             *metrics.Metrics
	// makeEvent builds the stored event (event id, RPZ blocked lookup,
	// is_internal flagging); supplied by main.
	makeEvent func(ts time.Time, clientIP string, qname string, qtype int, rcode int, latencyMS int) buffer.Event
}

// process validates msg and returns the event to enqueue for shipping.
//
// ok is false when the frame carries no shippable event — an unparseable
// response — or when the event is a prober-source event suppressed by
// dropProberEvents. In the suppressed case every metric has already been
// observed exactly as it would have been without the drop.
func (p responseProcessor) process(msg *dnstap.Message) (buffer.Event, bool) {
	if msg.GetType() != dnstap.Message_CLIENT_RESPONSE {
		return buffer.Event{}, false
	}

	ip := net.IP(msg.GetQueryAddress())
	if ip == nil {
		return buffer.Event{}, false
	}
	clientIP := ip.String()

	// Classify synthetic prober traffic by dnstap query source IP BEFORE
	// any histogram observation so prober samples are exported on separate
	// series and cannot contaminate production latency quantiles.
	isProber := p.probers.contains(clientIP)

	wire := msg.GetResponseMessage()
	if len(wire) == 0 {
		return buffer.Event{}, false
	}

	var dnsMsg dns.Msg
	if err := dnsMsg.Unpack(wire); err != nil {
		return buffer.Event{}, false
	}
	if len(dnsMsg.Question) == 0 {
		return buffer.Event{}, false
	}
	qname := dnsMsg.Question[0].Name
	qtype := int(dnsMsg.Question[0].Qtype)

	rcode := dnsMsg.Rcode

	latencyMS := 0
	if d, ok := dnstapLatency(msg); ok {
		// The stored event keeps its historic coarse field (integer
		// milliseconds, sub-ms truncates to 0); only the metrics
		// observation below uses the full nanosecond precision dnsdist
		// provides.
		latencyMS = int(d / time.Millisecond)
		p.mets.ObserveResponseLatency(isProber, d)
	}

	// Suppress the ship — never the metrics — of prober-source events.
	// Everything above this point runs identically with the drop on or
	// off; only the enqueue below is skipped.
	if isProber && p.dropProberEvents {
		return buffer.Event{}, false
	}

	ts := time.Now().UTC()
	if msg.GetResponseTimeSec() != 0 {
		ts = time.Unix(int64(msg.GetResponseTimeSec()), int64(msg.GetResponseTimeNsec())).UTC()
	} else if msg.GetQueryTimeSec() != 0 {
		ts = time.Unix(int64(msg.GetQueryTimeSec()), int64(msg.GetQueryTimeNsec())).UTC()
	}

	return p.makeEvent(ts, clientIP, qname, qtype, rcode, latencyMS), true
}
