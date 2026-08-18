package netutil

import "testing"

func TestParseSubnets(t *testing.T) {
	nets, err := ParseSubnets("172.30.0.0/24, 10.0.0.0/8")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(nets) != 2 {
		t.Fatalf("expected 2 subnets, got %d", len(nets))
	}

	if _, err := ParseSubnets("not-a-cidr"); err == nil {
		t.Fatal("expected error for invalid CIDR")
	}
}

func TestContainsIP(t *testing.T) {
	nets, err := ParseSubnets("172.30.0.0/24, fc00::/7")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	cases := []struct {
		ip   string
		want bool
	}{
		{"172.30.0.3", true},
		{"172.30.0.254", true},
		{"172.30.1.1", false},
		{"10.5.5.50", false},
		{"fd01:949f:9d51:573e:1::1", true},
		{"", false},
		{"garbage", false},
	}
	for _, c := range cases {
		if got := ContainsIP(nets, c.ip); got != c.want {
			t.Errorf("ContainsIP(%q) = %v, want %v", c.ip, got, c.want)
		}
	}

	if ContainsIP(nil, "172.30.0.3") {
		t.Error("nil subnet list should not match")
	}
}
