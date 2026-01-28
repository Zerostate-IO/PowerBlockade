package config

import (
	"os"
	"testing"
)

func TestParseBytes(t *testing.T) {
	tests := []struct {
		input    string
		expected int64
		wantErr  bool
	}{
		{"1024", 1024, false},
		{"1KB", 1024, false},
		{"1K", 1024, false},
		{"1MB", 1024 * 1024, false},
		{"1M", 1024 * 1024, false},
		{"1GB", 1024 * 1024 * 1024, false},
		{"1G", 1024 * 1024 * 1024, false},
		{"100MB", 100 * 1024 * 1024, false},
		{" 10 KB ", 10 * 1024, false},
		{"invalid", 0, true},
		{"", 0, true},
	}

	for _, tc := range tests {
		t.Run(tc.input, func(t *testing.T) {
			got, err := parseBytes(tc.input)
			if tc.wantErr {
				if err == nil {
					t.Errorf("expected error for input %q", tc.input)
				}
				return
			}
			if err != nil {
				t.Errorf("unexpected error: %v", err)
				return
			}
			if got != tc.expected {
				t.Errorf("parseBytes(%q) = %d, want %d", tc.input, got, tc.expected)
			}
		})
	}
}

func TestParseInt(t *testing.T) {
	tests := []struct {
		input    string
		expected int
		wantErr  bool
	}{
		{"123", 123, false},
		{" 456 ", 456, false},
		{"0", 0, false},
		{"-1", -1, false},
		{"abc", 0, true},
		{"", 0, true},
	}

	for _, tc := range tests {
		t.Run(tc.input, func(t *testing.T) {
			got, err := parseInt(tc.input)
			if tc.wantErr {
				if err == nil {
					t.Errorf("expected error for input %q", tc.input)
				}
				return
			}
			if err != nil {
				t.Errorf("unexpected error: %v", err)
				return
			}
			if got != tc.expected {
				t.Errorf("parseInt(%q) = %d, want %d", tc.input, got, tc.expected)
			}
		})
	}
}

func TestDefaultConfig(t *testing.T) {
	cfg := defaultConfig()

	if cfg.NodeName != "primary" {
		t.Errorf("NodeName = %q, want %q", cfg.NodeName, "primary")
	}
	if cfg.DnstapSocket != "/var/run/dnstap/dnstap.sock" {
		t.Errorf("DnstapSocket = %q, want default", cfg.DnstapSocket)
	}
	if cfg.Primary.URL != "http://admin-ui:8080" {
		t.Errorf("Primary.URL = %q, want default", cfg.Primary.URL)
	}
	if cfg.Buffer.MaxBytes != 100*1024*1024 {
		t.Errorf("Buffer.MaxBytes = %d, want 100MB", cfg.Buffer.MaxBytes)
	}
	if cfg.Buffer.MaxAge != 86400 {
		t.Errorf("Buffer.MaxAge = %d, want 86400", cfg.Buffer.MaxAge)
	}
	if cfg.Debug != false {
		t.Errorf("Debug = %v, want false", cfg.Debug)
	}
}

func TestLoadWithEnvOverrides(t *testing.T) {
	os.Setenv("NODE_NAME", "test-node")
	os.Setenv("PRIMARY_URL", "http://localhost:9999")
	os.Setenv("PRIMARY_API_KEY", "secret-key")
	os.Setenv("DEBUG_DNSTAP", "true")
	os.Setenv("BUFFER_MAX_BYTES", "50MB")
	os.Setenv("BUFFER_MAX_AGE", "3600")
	defer func() {
		os.Unsetenv("NODE_NAME")
		os.Unsetenv("PRIMARY_URL")
		os.Unsetenv("PRIMARY_API_KEY")
		os.Unsetenv("DEBUG_DNSTAP")
		os.Unsetenv("BUFFER_MAX_BYTES")
		os.Unsetenv("BUFFER_MAX_AGE")
	}()

	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load() error: %v", err)
	}

	if cfg.NodeName != "test-node" {
		t.Errorf("NodeName = %q, want %q", cfg.NodeName, "test-node")
	}
	if cfg.Primary.URL != "http://localhost:9999" {
		t.Errorf("Primary.URL = %q, want %q", cfg.Primary.URL, "http://localhost:9999")
	}
	if cfg.Primary.APIKey != "secret-key" {
		t.Errorf("Primary.APIKey = %q, want %q", cfg.Primary.APIKey, "secret-key")
	}
	if cfg.Debug != true {
		t.Errorf("Debug = %v, want true", cfg.Debug)
	}
	if cfg.Buffer.MaxBytes != 50*1024*1024 {
		t.Errorf("Buffer.MaxBytes = %d, want 50MB", cfg.Buffer.MaxBytes)
	}
	if cfg.Buffer.MaxAge != 3600 {
		t.Errorf("Buffer.MaxAge = %d, want 3600", cfg.Buffer.MaxAge)
	}
}

func TestLoadWithGELFConfig(t *testing.T) {
	os.Setenv("GELF_ENABLED", "yes")
	os.Setenv("GELF_ENDPOINT", "gelf.example.com:12201")
	defer func() {
		os.Unsetenv("GELF_ENABLED")
		os.Unsetenv("GELF_ENDPOINT")
	}()

	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load() error: %v", err)
	}

	if !cfg.GELF.Enabled {
		t.Errorf("GELF.Enabled = false, want true")
	}
	if cfg.GELF.Endpoint != "gelf.example.com:12201" {
		t.Errorf("GELF.Endpoint = %q, want %q", cfg.GELF.Endpoint, "gelf.example.com:12201")
	}
}
