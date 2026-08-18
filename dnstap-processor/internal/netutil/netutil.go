package netutil

import (
	"net"
	"strings"
)

// ParseSubnets parses comma/space separated CIDR strings into IPNets.
func ParseSubnets(raw string) ([]*net.IPNet, error) {
	var nets []*net.IPNet
	for _, part := range strings.FieldsFunc(raw, func(r rune) bool {
		return r == ',' || r == ' ' || r == '\t' || r == '\n'
	}) {
		part = strings.TrimSpace(part)
		if part == "" {
			continue
		}
		_, ipNet, err := net.ParseCIDR(part)
		if err != nil {
			return nil, err
		}
		nets = append(nets, ipNet)
	}
	return nets, nil
}

// ContainsIP reports whether ipStr is inside any of the given subnets.
// A nil/empty ipStr or empty subnet list returns false.
func ContainsIP(nets []*net.IPNet, ipStr string) bool {
	ip := net.ParseIP(ipStr)
	if ip == nil || len(nets) == 0 {
		return false
	}
	for _, n := range nets {
		if n.Contains(ip) {
			return true
		}
	}
	return false
}
