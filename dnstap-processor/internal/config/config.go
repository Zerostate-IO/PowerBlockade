package config

import (
  "fmt"
  "os"
  "strings"

  "gopkg.in/yaml.v3"
)

type OpenSearchConfig struct {
  URL         string `yaml:"url"`
  IndexPrefix string `yaml:"index_prefix"`
}

type PrimaryConfig struct {
  URL    string `yaml:"url"`
  APIKey string `yaml:"api_key"`
}

type GELFConfig struct {
  Enabled  bool   `yaml:"enabled"`
  Endpoint string `yaml:"endpoint"`
}

type Config struct {
  NodeName     string          `yaml:"node_name"`
  DnstapSocket string          `yaml:"dnstap_socket"`
  ProtobufListen string        `yaml:"protobuf_listen"`
  Primary      PrimaryConfig   `yaml:"primary"`
  GELF         GELFConfig       `yaml:"gelf"`
  Debug        bool            `yaml:"debug"`
}

func defaultConfig() Config {
  return Config{
    NodeName:     "primary",
    DnstapSocket: "/var/run/dnstap/dnstap.sock",
    ProtobufListen: "0.0.0.0:50001",
    Primary: PrimaryConfig{
      URL:    "http://admin-ui:8080",
      APIKey: "",
    },
    GELF: GELFConfig{Enabled: false, Endpoint: ""},
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

  return cfg, nil
}
