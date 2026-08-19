// Package config loads prober settings from PROBE_* environment variables.
package config

import (
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/miekg/dns"
)

// Config holds all prober settings. Every knob is optional; defaults match
// the compose stanza: one full corpus pass every 60s with ±10% jitter,
// 2s per-query timeout, A queries against dnsdist:53.
type Config struct {
	Target      string        // host:port of the DNS edge to probe
	CorpusPath  string        // path to the frozen control corpus
	Interval    time.Duration // sleep between pass end and next pass start, before jitter
	JitterPct   float64       // ± percentage applied to Interval (0 disables jitter)
	Timeout     time.Duration // per-query timeout; a timeout is never retried
	QTypes      []string      // query types sent for every corpus domain (uppercase)
	MetricsAddr string        // listen address for the /metrics endpoint
}

// Defaults for unset environment variables.
const (
	DefaultTarget      = "dnsdist:53"
	DefaultCorpusPath  = "/usr/local/share/powerblockade/corpus/control-domains.txt"
	DefaultMetricsAddr = ":9533"
	DefaultInterval    = 60 * time.Second
	DefaultTimeout     = 2 * time.Second
	DefaultJitterPct   = 10.0
)

// Load reads the environment and validates the result. Unknown query types,
// non-positive durations, and out-of-range jitter are configuration errors.
func Load() (Config, error) {
	cfg := Config{
		Target:      envDefault("PROBE_TARGET", DefaultTarget),
		CorpusPath:  envDefault("PROBE_CORPUS", DefaultCorpusPath),
		MetricsAddr: envDefault("PROBE_METRICS_ADDR", DefaultMetricsAddr),
		Interval:    DefaultInterval,
		Timeout:     DefaultTimeout,
		JitterPct:   DefaultJitterPct,
	}

	if v := strings.TrimSpace(os.Getenv("PROBE_INTERVAL")); v != "" {
		d, err := time.ParseDuration(v)
		if err != nil {
			return Config{}, fmt.Errorf("PROBE_INTERVAL: %w", err)
		}
		if d <= 0 {
			return Config{}, fmt.Errorf("PROBE_INTERVAL must be positive, got %s", d)
		}
		cfg.Interval = d
	}

	if v := strings.TrimSpace(os.Getenv("PROBE_TIMEOUT")); v != "" {
		d, err := time.ParseDuration(v)
		if err != nil {
			return Config{}, fmt.Errorf("PROBE_TIMEOUT: %w", err)
		}
		if d <= 0 {
			return Config{}, fmt.Errorf("PROBE_TIMEOUT must be positive, got %s", d)
		}
		cfg.Timeout = d
	}

	if v := strings.TrimSpace(os.Getenv("PROBE_JITTER_PCT")); v != "" {
		p, err := strconv.ParseFloat(v, 64)
		if err != nil {
			return Config{}, fmt.Errorf("PROBE_JITTER_PCT: %w", err)
		}
		if p < 0 || p > 100 {
			return Config{}, fmt.Errorf("PROBE_JITTER_PCT must be between 0 and 100, got %g", p)
		}
		cfg.JitterPct = p
	}

	cfg.QTypes = []string{"A"}
	if v := strings.TrimSpace(os.Getenv("PROBE_QTYPES")); v != "" {
		var qtypes []string
		for _, s := range strings.Split(v, ",") {
			s = strings.ToUpper(strings.TrimSpace(s))
			if s == "" {
				continue
			}
			if _, ok := dns.StringToType[s]; !ok {
				return Config{}, fmt.Errorf("PROBE_QTYPES: unknown query type %q", s)
			}
			qtypes = append(qtypes, s)
		}
		if len(qtypes) == 0 {
			return Config{}, fmt.Errorf("PROBE_QTYPES must contain at least one query type")
		}
		cfg.QTypes = qtypes
	}

	if cfg.Target == "" {
		return Config{}, fmt.Errorf("PROBE_TARGET must not be empty")
	}

	return cfg, nil
}

func envDefault(key, def string) string {
	if v := strings.TrimSpace(os.Getenv(key)); v != "" {
		return v
	}
	return def
}
