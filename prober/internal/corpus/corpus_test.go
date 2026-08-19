package corpus

import (
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

func writeTemp(t *testing.T, content string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "corpus.txt")
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestLoadParsesCommentsBlanksAndDefaults(t *testing.T) {
	path := writeTemp(t, `# header comment
google.com A
cloudflare.com

	# indented comment, whitespace-prefixed

example.org AAAA
single-token.example
MIXEDcase.EXAMPLE a
`)

	got, err := Load(path)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	want := []Query{
		{Name: "google.com", QType: "A"},
		{Name: "cloudflare.com", QType: "A"},
		{Name: "example.org", QType: "AAAA"},
		{Name: "single-token.example", QType: "A"},
		{Name: "MIXEDcase.EXAMPLE", QType: "A"},
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
}

func TestLoadPreservesOrder(t *testing.T) {
	lines := "b.example A\na.example A\nc.example A\n"
	got, err := Load(writeTemp(t, lines))
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	for i, name := range []string{"b.example", "a.example", "c.example"} {
		if got[i].Name != name {
			t.Fatalf("entry %d = %q, want %q", i, got[i].Name, name)
		}
	}
}

func TestLoadRejectsMalformedLines(t *testing.T) {
	if _, err := Load(writeTemp(t, "example.com A extra\n")); err == nil {
		t.Fatal("expected error for line with more than two fields")
	}
}

func TestLoadMissingFile(t *testing.T) {
	if _, err := Load(filepath.Join(t.TempDir(), "nope.txt")); err == nil {
		t.Fatal("expected error for missing file")
	}
}

func TestLoadEmptyCorpus(t *testing.T) {
	if _, err := Load(writeTemp(t, "# only comments\n\n")); err == nil {
		t.Fatal("expected error for corpus with no queries")
	}
}
