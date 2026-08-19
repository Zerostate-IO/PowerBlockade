// Package corpus loads the frozen control-domain list used for probing.
package corpus

import (
	"bufio"
	"fmt"
	"os"
	"strings"
)

// Query is one entry of the control corpus: a domain name and a query type.
// The on-disk format is "<domain> <qtype>" per line, with "#" comments and
// blank lines ignored. A missing qtype column defaults to "A".
type Query struct {
	Name  string
	QType string
}

// Load reads a corpus file. It preserves file order (the corpus is the
// deterministic walk order), deduplicates nothing, and rejects lines that
// carry more than one token after the qtype so a malformed corpus fails
// loudly instead of silently probing the wrong thing.
func Load(path string) ([]Query, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("open corpus: %w", err)
	}
	defer f.Close()

	var queries []Query
	scanner := bufio.NewScanner(f)
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)
	lineNo := 0
	for scanner.Scan() {
		lineNo++
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		fields := strings.Fields(line)
		if len(fields) == 1 {
			queries = append(queries, Query{Name: fields[0], QType: "A"})
			continue
		}
		if len(fields) > 2 {
			return nil, fmt.Errorf("corpus line %d: expected \"<domain> [qtype]\", got %q", lineNo, line)
		}
		queries = append(queries, Query{Name: fields[0], QType: strings.ToUpper(fields[1])})
	}
	if err := scanner.Err(); err != nil {
		return nil, fmt.Errorf("read corpus: %w", err)
	}
	if len(queries) == 0 {
		return nil, fmt.Errorf("corpus %s contains no queries", path)
	}
	return queries, nil
}
