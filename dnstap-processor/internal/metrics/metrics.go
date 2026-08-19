// Package metrics defines the Prometheus metrics dnstap-processor exposes
// on its /metrics endpoint.
//
// The edge latency histogram is observed in-process at the full precision
// dnsdist provides (nanosecond dnstap query_time/response_time), before
// events are serialized. The buffered event payload keeps its coarse
// integer-millisecond latency_ms field; only the metrics path is precise.
//
// Prober traffic (dnstap query source addresses listed in PROBER_IPS) is
// classified before observation and exported on its own prober="true"
// histogram series, so production quantiles (prober="false") cannot be
// contaminated by synthetic measurements.
package metrics

import (
	"net/http"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

// DefaultListen is the default address the /metrics endpoint binds to.
const DefaultListen = "0.0.0.0:9422"

// LatencyBuckets are the histogram upper bounds, in seconds, for edge
// response latency: 0.1, 0.25, 0.5, 1, 2.5, 5, and 10 ms. These resolve
// sub-millisecond tail latencies that integer-millisecond event latency
// rounds away.
var LatencyBuckets = []float64{0.0001, 0.00025, 0.0005, 0.001, 0.0025, 0.005, 0.01}

// Values of the histogram "prober" label. Each value is an independent
// time series; observations made with one value never affect the other.
const (
	ProberLabelTrue  = "true"
	ProberLabelFalse = "false"
)

// Metrics bundles every metric dnstap-processor exports. All collectors are
// registered on a dedicated registry so the /metrics output contains exactly
// these series and unit tests can instantiate isolated copies.
type Metrics struct {
	registry *prometheus.Registry

	// ResponseLatency is the dnsdist edge latency (dnstap CLIENT_RESPONSE
	// response_time minus query_time), in seconds, observed at full
	// precision before event serialization. Split by the "prober" label.
	ResponseLatency *prometheus.HistogramVec

	// EventsReceived counts dnstap frames received from dnsdist.
	EventsReceived prometheus.Counter

	// EventsBuffered counts events written to the on-disk buffer.
	EventsBuffered prometheus.Counter

	// EventsShipped counts events accepted by the primary ingest API.
	EventsShipped prometheus.Counter

	// EventsDropped counts events lost to backpressure or buffer failures.
	EventsDropped prometheus.Counter

	// BufferPending is the number of events currently waiting in the
	// on-disk buffer.
	BufferPending prometheus.Gauge
}

// New constructs a Metrics bundle with all collectors registered.
func New() *Metrics {
	m := &Metrics{
		registry: prometheus.NewRegistry(),
		ResponseLatency: prometheus.NewHistogramVec(
			prometheus.HistogramOpts{
				Namespace: "dnstap_processor",
				Name:      "response_latency_seconds",
				Help:      "Edge response latency (dnstap CLIENT_RESPONSE response_time minus query_time) observed at nanosecond precision; sub-millisecond buckets resolve latencies the integer-millisecond event field rounds away. Synthetic prober traffic is exported on the separate prober=\"true\" series.",
				Buckets:   LatencyBuckets,
			},
			[]string{"prober"},
		),
		EventsReceived: prometheus.NewCounter(prometheus.CounterOpts{
			Namespace: "dnstap_processor",
			Name:      "events_received_total",
			Help:      "dnstap frames received from dnsdist.",
		}),
		EventsBuffered: prometheus.NewCounter(prometheus.CounterOpts{
			Namespace: "dnstap_processor",
			Name:      "events_buffered_total",
			Help:      "Events written to the on-disk buffer.",
		}),
		EventsShipped: prometheus.NewCounter(prometheus.CounterOpts{
			Namespace: "dnstap_processor",
			Name:      "events_shipped_total",
			Help:      "Events accepted by the primary ingest API.",
		}),
		EventsDropped: prometheus.NewCounter(prometheus.CounterOpts{
			Namespace: "dnstap_processor",
			Name:      "events_dropped_total",
			Help:      "Events dropped under backpressure or lost on buffer write failure.",
		}),
		BufferPending: prometheus.NewGauge(prometheus.GaugeOpts{
			Namespace: "dnstap_processor",
			Name:      "buffer_pending",
			Help:      "Events currently pending in the on-disk buffer.",
		}),
	}

	m.registry.MustRegister(
		m.ResponseLatency,
		m.EventsReceived,
		m.EventsBuffered,
		m.EventsShipped,
		m.EventsDropped,
		m.BufferPending,
	)
	return m
}

// ObserveResponseLatency records one edge latency observation on the prober
// or production series. prober must be decided from the dnstap query source
// address before this call. Non-positive durations are ignored: they carry
// no latency signal (missing or inverted timestamps).
func (m *Metrics) ObserveResponseLatency(prober bool, d time.Duration) {
	if d <= 0 {
		return
	}
	label := ProberLabelFalse
	if prober {
		label = ProberLabelTrue
	}
	m.ResponseLatency.WithLabelValues(label).Observe(d.Seconds())
}

// Handler returns the HTTP handler serving the Prometheus exposition format.
func (m *Metrics) Handler() http.Handler {
	return promhttp.HandlerFor(m.registry, promhttp.HandlerOpts{})
}
