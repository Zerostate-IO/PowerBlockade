package config

import (
	"reflect"
	"strings"
	"testing"
	"time"
)

func TestLoadDefaults(t *testing.T) {
	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if cfg.Target != "dnsdist:53" {
		t.Errorf("Target = %q, want dnsdist:53", cfg.Target)
	}
	if cfg.Interval != 60*time.Second {
		t.Errorf("Interval = %v, want 60s", cfg.Interval)
	}
	if cfg.JitterPct != 10.0 {
		t.Errorf("JitterPct = %v, want 10", cfg.JitterPct)
	}
	if cfg.Timeout != 2*time.Second {
		t.Errorf("Timeout = %v, want 2s", cfg.Timeout)
	}
	if !reflect.DeepEqual(cfg.QTypes, []string{"A"}) {
		t.Errorf("QTypes = %v, want [A]", cfg.QTypes)
	}
}

func TestLoadEnvOverrides(t *testing.T) {
	t.Setenv("PROBE_TARGET", "127.0.0.1:5353")
	t.Setenv("PROBE_INTERVAL", "5m")
	t.Setenv("PROBE_JITTER_PCT", "25")
	t.Setenv("PROBE_TIMEOUT", "750ms")
	t.Setenv("PROBE_QTYPES", "a, AAAA , txt")
	t.Setenv("PROBE_CORPUS", "/tmp/c.txt")
	t.Setenv("PROBE_METRICS_ADDR", ":9999")

	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if cfg.Target != "127.0.0.1:5353" {
		t.Errorf("Target = %q", cfg.Target)
	}
	if cfg.Interval != 5*time.Minute {
		t.Errorf("Interval = %v", cfg.Interval)
	}
	if cfg.JitterPct != 25 {
		t.Errorf("JitterPct = %v", cfg.JitterPct)
	}
	if cfg.Timeout != 750*time.Millisecond {
		t.Errorf("Timeout = %v", cfg.Timeout)
	}
	if want := []string{"A", "AAAA", "TXT"}; !reflect.DeepEqual(cfg.QTypes, want) {
		t.Errorf("QTypes = %v, want %v", cfg.QTypes, want)
	}
	if cfg.CorpusPath != "/tmp/c.txt" {
		t.Errorf("CorpusPath = %q", cfg.CorpusPath)
	}
	if cfg.MetricsAddr != ":9999" {
		t.Errorf("MetricsAddr = %q", cfg.MetricsAddr)
	}
}

func TestLoadRejectsBadValues(t *testing.T) {
	cases := []struct {
		key, val, wantErr string
	}{
		{"PROBE_INTERVAL", "not-a-duration", "PROBE_INTERVAL"},
		{"PROBE_INTERVAL", "0s", "PROBE_INTERVAL"},
		{"PROBE_TIMEOUT", "-1s", "PROBE_TIMEOUT"},
		{"PROBE_JITTER_PCT", "150", "PROBE_JITTER_PCT"},
		{"PROBE_JITTER_PCT", "-5", "PROBE_JITTER_PCT"},
		{"PROBE_QTYPES", "A,BOGUS", "PROBE_QTYPES"},
		{"PROBE_QTYPES", ",", "PROBE_QTYPES"},
	}
	for _, c := range cases {
		// Subtests keep t.Setenv scoped per case; a shared loop would leak
		// each case's variables into the next.
		t.Run(c.key+"="+c.val, func(t *testing.T) {
			t.Setenv(c.key, c.val)
			_, err := Load()
			if err == nil {
				t.Fatalf("expected error")
			}
			if !strings.Contains(err.Error(), c.wantErr) {
				t.Fatalf("error %q does not mention %q", err, c.wantErr)
			}
		})
	}
}
