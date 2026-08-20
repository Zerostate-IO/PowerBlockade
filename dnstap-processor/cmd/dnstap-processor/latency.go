package main

import (
	"strings"
	"time"

	"github.com/dnstap/golang-dnstap"
)

// dnstapLatency computes the edge latency between a dnstap CLIENT_RESPONSE
// message's query_time and response_time timestamps, preserving the
// nanosecond precision dnsdist 2.0.x provides.
//
// ok is false when either timestamp is missing or the response does not
// follow the query; those frames carry no latency signal. Callers must keep
// deriving the coarse integer-millisecond event field with
// int(d/time.Millisecond) — only the metrics observation path uses the full
// precision duration.
func dnstapLatency(msg *dnstap.Message) (time.Duration, bool) {
	qSec := msg.GetQueryTimeSec()
	rSec := msg.GetResponseTimeSec()
	if qSec == 0 || rSec == 0 {
		return 0, false
	}
	qts := time.Unix(int64(qSec), int64(msg.GetQueryTimeNsec()))
	rts := time.Unix(int64(rSec), int64(msg.GetResponseTimeNsec()))
	d := rts.Sub(qts)
	if d <= 0 {
		return 0, false
	}
	return d, true
}

// proberIPs holds dnstap query source addresses whose traffic is synthetic
// prober traffic. Membership is decided before histogram observation so
// prober samples are exported on their own series and never enter the
// production latency quantiles.
type proberIPs map[string]struct{}

// parseProberIPs parses a comma-separated address list. Whitespace is
// trimmed; empty entries are ignored.
func parseProberIPs(commaList string) proberIPs {
	m := proberIPs{}
	for _, s := range strings.Split(commaList, ",") {
		if s = strings.TrimSpace(s); s != "" {
			m[s] = struct{}{}
		}
	}
	return m
}

func (p proberIPs) contains(ip string) bool {
	_, ok := p[ip]
	return ok
}
