package main

import (
	"context"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/miekg/dns"
	"github.com/prometheus/client_golang/prometheus/promhttp"

	"github.com/powerblockade/prober/internal/config"
	"github.com/powerblockade/prober/internal/corpus"
	"github.com/powerblockade/prober/internal/prober"
)

var (
	Version = "0.1.0-dev"
	GitSHA  = "unknown"
)

func main() {
	cfg, err := config.Load()
	if err != nil {
		log.Fatalf("config: %v", err)
	}

	queries, err := corpus.Load(cfg.CorpusPath)
	if err != nil {
		log.Fatalf("corpus: %v", err)
	}

	qtypes := make([]uint16, 0, len(cfg.QTypes))
	for _, s := range cfg.QTypes {
		qtypes = append(qtypes, dns.StringToType[s])
	}

	p := prober.New(cfg.Target, cfg.Timeout)
	defer p.Close()

	log.Printf(
		"starting prober version=%s sha=%s target=%s corpus=%s (%d domains, %d qtypes, %d queries/pass) interval=%s jitter=±%g%% timeout=%s metrics=%s",
		Version, GitSHA, cfg.Target, cfg.CorpusPath,
		len(queries), len(qtypes), len(queries)*len(qtypes),
		cfg.Interval, cfg.JitterPct, cfg.Timeout, cfg.MetricsAddr,
	)

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	// Metrics endpoint. Not published to the host; Prometheus scrapes it
	// over the compose network.
	mux := http.NewServeMux()
	mux.Handle("/metrics", promhttp.HandlerFor(prober.Registry, promhttp.HandlerOpts{}))
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok"))
	})
	server := &http.Server{Addr: cfg.MetricsAddr, Handler: mux}
	go func() {
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("metrics server: %v", err)
		}
	}()

	// Pass cadence: each pass starts interval±jitter after the previous one
	// started; a pass that overruns its interval shortens the sleep (never
	// below zero).
	runPasses(ctx, p, queries, qtypes, cfg)

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	_ = server.Shutdown(shutdownCtx)
	log.Printf("prober stopped")
}

func runPasses(ctx context.Context, p *prober.Prober, queries []corpus.Query, qtypes []uint16, cfg config.Config) {
	for {
		passStart := time.Now()
		sent := 0
		for _, q := range queries {
			for _, qt := range qtypes {
				result, latency := p.Query(q.Name, qt)
				sent++
				if result == prober.ResultTimedOut {
					log.Printf("timeout: %s %s after %s", q.QType, q.Name, latency.Round(time.Microsecond))
				}
				if ctx.Err() != nil {
					return
				}
			}
		}
		elapsed := time.Since(passStart)
		prober.ObservePass(elapsed, sent)
		log.Printf("pass complete: %d queries in %s", sent, elapsed.Round(time.Millisecond))

		sleep := p.JitterSleep(cfg.Interval, cfg.JitterPct) - elapsed
		if sleep < 0 {
			sleep = 0
		}
		select {
		case <-ctx.Done():
			return
		case <-time.After(sleep):
		}
	}
}
