package config

import (
	"fmt"
	"os"
	"strconv"
	"strings"

	"gopkg.in/yaml.v3"
)

func parseBytes(s string) (int64, error) {
	s = strings.TrimSpace(strings.ToUpper(s))
	multiplier := int64(1)
	if strings.HasSuffix(s, "GB") || strings.HasSuffix(s, "G") {
		multiplier = 1024 * 1024 * 1024
		s = strings.TrimSuffix(strings.TrimSuffix(s, "GB"), "G")
	} else if strings.HasSuffix(s, "MB") || strings.HasSuffix(s, "M") {
		multiplier = 1024 * 1024
		s = strings.TrimSuffix(strings.TrimSuffix(s, "MB"), "M")
	} else if strings.HasSuffix(s, "KB") || strings.HasSuffix(s, "K") {
		multiplier = 1024
		s = strings.TrimSuffix(strings.TrimSuffix(s, "KB"), "K")
	}
	n, err := strconv.ParseInt(strings.TrimSpace(s), 10, 64)
	if err != nil {
		return 0, err
	}
	return n * multiplier, nil
}

func parseInt(s string) (int, error) {
	n, err := strconv.Atoi(strings.TrimSpace(s))
	return n, err
}

type PrimaryConfig struct {
	URL    string `yaml:"url"`
	APIKey string `yaml:"api_key"`
}

type GELFConfig struct {
	Enabled  bool   `yaml:"enabled"`
	Endpoint string `yaml:"endpoint"`
}

type BufferConfig struct {
	Path     string `yaml:"path"`
	MaxBytes int64  `yaml:"max_bytes"`
	MaxAge   int    `yaml:"max_age_seconds"`
}

type Config struct {
	NodeName       string        `yaml:"node_name"`
	DnstapSocket   string        `yaml:"dnstap_socket"`
	DnstapListen   string        `yaml:"dnstap_listen"` // TCP listener for dnstap (optional, overrides socket)
	ProtobufListen string        `yaml:"protobuf_listen"`
	Primary        PrimaryConfig `yaml:"primary"`
	GELF           GELFConfig    `yaml:"gelf"`
	Buffer         BufferConfig  `yaml:"buffer"`
	Debug          bool          `yaml:"debug"`
}

func defaultConfig() Config {
	return Config{
		NodeName:       "primary",
		DnstapSocket:   "/var/run/dnstap/dnstap.sock",
		ProtobufListen: "0.0.0.0:50001",
		Primary: PrimaryConfig{
			URL:    "http://admin-ui:8080",
			APIKey: "",
		},
		GELF: GELFConfig{Enabled: false, Endpoint: ""},
		Buffer: BufferConfig{
			Path:     "/var/lib/dnstap-processor/buffer.db",
			MaxBytes: 100 * 1024 * 1024, // 100MB
			MaxAge:   86400,             // 24 hours
		},
		Debug: false,
	}
}

func Load() (Config, error) {
	cfg := defaultConfig()

	// Optional YAML file
	if path := strings.TrimSpace(os.Getenv("CONFIG_PATH")); path != "" {
		b, err := os.ReadFile(path)
		if err != nil {
			return Config{}, fmt.Errorf("read %s: %w", path, err)
		}
		if err := yaml.Unmarshal(b, &cfg); err != nil {
			return Config{}, fmt.Errorf("parse %s: %w", path, err)
		}
	}

	// Env overrides (match docker-compose.yml)
	if v := strings.TrimSpace(os.Getenv("NODE_NAME")); v != "" {
		cfg.NodeName = v
	}
	if v := strings.TrimSpace(os.Getenv("DNSTAP_SOCKET")); v != "" {
		cfg.DnstapSocket = v
	}
	if v := strings.TrimSpace(os.Getenv("DNSTAP_LISTEN")); v != "" {
		cfg.DnstapListen = v
	}
	if v := strings.TrimSpace(os.Getenv("PROTOBUF_LISTEN")); v != "" {
		cfg.ProtobufListen = v
	}
	if v := strings.TrimSpace(os.Getenv("PRIMARY_URL")); v != "" {
		cfg.Primary.URL = v
	}
	if v := strings.TrimSpace(os.Getenv("PRIMARY_API_KEY")); v != "" {
		cfg.Primary.APIKey = v
	}
	if v := strings.TrimSpace(os.Getenv("GELF_ENDPOINT")); v != "" {
		cfg.GELF.Endpoint = v
	}
	if v := strings.TrimSpace(os.Getenv("GELF_ENABLED")); v != "" {
		cfg.GELF.Enabled = v == "1" || strings.EqualFold(v, "true") || strings.EqualFold(v, "yes")
	}

	if v := strings.TrimSpace(os.Getenv("DEBUG_DNSTAP")); v != "" {
		cfg.Debug = v == "1" || strings.EqualFold(v, "true") || strings.EqualFold(v, "yes")
	}

	if v := strings.TrimSpace(os.Getenv("BUFFER_PATH")); v != "" {
		cfg.Buffer.Path = v
	}
	if v := strings.TrimSpace(os.Getenv("BUFFER_MAX_BYTES")); v != "" {
		if n, err := parseBytes(v); err == nil {
			cfg.Buffer.MaxBytes = n
		}
	}
	if v := strings.TrimSpace(os.Getenv("BUFFER_MAX_AGE")); v != "" {
		if n, err := parseInt(v); err == nil {
			cfg.Buffer.MaxAge = n
		}
	}

	return cfg, nil
}
